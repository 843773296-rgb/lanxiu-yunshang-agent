#!/usr/bin/env python3
"""按澜绣云裳 PRD 的状态机与业务规则生成模拟数据。

每条异常案例都带 _truth 字段(已知真因),仅用于评测比对,
不通过任何 agent 可见的接口暴露。
"""
import sqlite3, sys, json, os, random

HERE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.join(HERE,"lanxiu.db")
random.seed(20260830)   # 固定种子,数据可复现

SCHEMA="""
DROP TABLE IF EXISTS points_log; DROP TABLE IF EXISTS member_bind; DROP TABLE IF EXISTS customer; DROP TABLE IF EXISTS deposit; DROP TABLE IF EXISTS refund_trace;
DROP TABLE IF EXISTS payment_flow; DROP TABLE IF EXISTS appointment; DROP TABLE IF EXISTS followup;
DROP TABLE IF EXISTS task; DROP TABLE IF EXISTS truth;
CREATE TABLE customer(id TEXT PRIMARY KEY, name TEXT, phone TEXT, phone_tail TEXT, shop TEXT,
  advisor TEXT, lifecycle TEXT, level TEXT, created TEXT, order_cnt INT, paid_amount REAL,
  last_interact TEXT, addr TEXT, birthday TEXT, archived INT DEFAULT 0,
  first_order TEXT, orders_12m INT DEFAULT 0, quarters_12m INT DEFAULT 0, amount_12m REAL DEFAULT 0,
  idle_days INT DEFAULT 0, matched TEXT, manual_lc TEXT, manual_at TEXT,
  gender TEXT, email TEXT, wechat TEXT, occupation TEXT, income TEXT, car TEXT,
  province TEXT, city TEXT, district TEXT, inviter TEXT, points INT DEFAULT 0, remark TEXT,
  -- 这条门店档案属于哪个账户(按手机号归)。**同一账户可以有多条档案** ——
  -- 在不同店建过档就是两条,「客户合并」工单要解决的正是这个。
  account_id TEXT);
-- 积分流水(设计稿 积分行为:账户调加/账户调减/积分消费/积分返还/确认款样/完成定购)
CREATE TABLE points_log(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT, behavior TEXT,
  delta INT, balance INT, ref_id TEXT, reason TEXT, actor TEXT, ts TEXT);
-- 绑定关系(设计稿 客户详情-绑定关系:邀请人 / 联系人)
CREATE TABLE member_bind(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT, kind TEXT,
  target_id TEXT, target_name TEXT, ts TEXT);
CREATE TABLE deposit(id TEXT PRIMARY KEY, customer_id TEXT, appt_id TEXT, amount REAL,
  status TEXT, idem_key TEXT, created TEXT, updated TEXT);
CREATE TABLE refund_trace(id INTEGER PRIMARY KEY AUTOINCREMENT, deposit_id TEXT, attempt INT,
  ts TEXT, channel TEXT, req_amount REAL, resp_code TEXT, resp_msg TEXT, idem_key TEXT);
CREATE TABLE payment_flow(id TEXT PRIMARY KEY, deposit_id TEXT, direction TEXT, amount REAL,
  channel TEXT, channel_serial TEXT, status TEXT, ts TEXT);
CREATE TABLE appointment(id TEXT PRIMARY KEY, customer_id TEXT, shop TEXT, advisor TEXT,
  start_ts TEXT, end_ts TEXT, status TEXT, deposit_id TEXT, checkin_ts TEXT);
CREATE TABLE followup(id TEXT PRIMARY KEY, customer_id TEXT, appt_id TEXT, ts TEXT,
  channel TEXT, content TEXT, advisor TEXT);
CREATE TABLE task(id TEXT PRIMARY KEY, type TEXT, ref_id TEXT, status TEXT, created TEXT, summary TEXT);
-- 研判台账 —— 平台和展示件的分界就在这张表:
-- 展示件跑一条、显示、忘掉;平台跑一条、落库、等人销账。
-- 同一条工单研判多次就是多行,谁都能回头看当时智能体说了什么、花了多少钱。
CREATE TABLE triage(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  schedule_id TEXT, breakpoint TEXT, case_id TEXT, created TEXT,
  ai_root_cause TEXT, ai_action TEXT, ai_evidence TEXT,
  ai_confidence TEXT,          -- 高 / 中 / 低,由工具调用数与证据完整度推,不是模型自称
  ai_text TEXT, tool_calls INT, cost REAL, latency_ms INT, model TEXT,
  in_tokens INT, out_tokens INT, cache_read INT,   -- 按 DeepSeek 实价算成本要用,顺便看缓存命中
  -- 回答体检:被打回过没有、因为什么。**这是「模型有多不听话」的直接度量** ——
  -- 比事后抽样评测灵敏得多,因为它是全量的。
  guard_blocked INT DEFAULT 0, guard_violations TEXT, answer_turns INT DEFAULT 1,

  status TEXT,                 -- 待复核 / 已采纳 / 已改判 / 已升级
  human_root_cause TEXT, human_action TEXT, human_note TEXT,
  handler TEXT, handled_at TEXT,
  into_eval INT DEFAULT 0      -- 人工改判后是否已回流评测集
);
CREATE TABLE shop(code TEXT PRIMARY KEY, name TEXT, status TEXT, manager TEXT,
  phone TEXT, province TEXT, addr TEXT, updated TEXT);
CREATE TABLE staff(no TEXT PRIMARY KEY, name TEXT, role TEXT, shop TEXT, status TEXT,
  updated_by TEXT, updated TEXT,
  -- 登录凭据。**员工才是后台的使用者**,而原来只有消费者账户(account)有密码,
  -- 员工一个都没有 —— 于是「你是店长还是顾问」只能靠请求里自称的字符串。
  -- 一条链上有一环是约定,整条链就只有约定那么强。
  login_name TEXT UNIQUE, pwd_algo TEXT, pwd_salt TEXT, pwd_hash TEXT,
  fail_count INT DEFAULT 0, locked_until TEXT, last_login TEXT,
  -- 顾问在业务侧的编号(A01…)。客户档案里的「归属顾问」历来存的是
  -- 「A01 林岚」这种显示串,和工号是**两套编号**;把 A 号放进花名册,
  -- 两套之间才有一个能查的桥,而不是靠名字连(名字既不唯一也会改)。
  adv_code TEXT);
CREATE TABLE schedule(id TEXT PRIMARY KEY, type TEXT, advisor TEXT, customer_id TEXT,
  start_ts TEXT, end_ts TEXT, status TEXT, summary TEXT, cancel_reason TEXT, shop TEXT,
  -- ── 排任务用的三列 ──────────────────────────────────────────────
  -- **同一个人两套编号**:schedule.advisor 是「A01 林岚」,staff 是工号 60000002,
  -- 原来只能靠名字连 —— 而名字既不唯一也会改。补一列工号做真正的关联。
  assignee_no TEXT,          -- 派给谁(staff.no)
  assigned_by TEXT,          -- 谁派的(staff.no)。**排任务必须记得住是谁派的**
  assigned_at TEXT,          -- 什么时候派的
  note TEXT,                 -- 日程描述(这件事要做什么)
  activity_code TEXT,        -- 绑定活动(activity.code)。可空 —— 大多数任务和活动无关
  -- 挂的单据号。**类型决定它是哪种单**:客户号 / 订单号 / 维保单号 / 售后单号。
  -- customer_id 不由人填,从这张单据带出来 —— 手填就有两个来源,而两个来源必然漂。
  ref_id TEXT,
  -- ── 改派留下的三列 ────────────────────────────────────────────────
  -- **改派不是「换个 assignee_no」。** 悄悄换掉的话,原来那个人的列表
  -- 凭空少一行 —— 他不会去问「我那条活呢」,他会以为自己记错了。
  -- 所以要留下「原来是谁的」,让他还看得见这条,并且看得见是谁拿走的、为什么。
  reassigned_from TEXT,      -- 改派前是谁的(staff.no)
  reassign_reason TEXT,      -- 为什么改派。**必填** —— 把人的活拿走要给个说法
  reassigned_at TEXT);
-- 任务附件。**派单时的图和总结时的图是两回事**,所以用 kind 分开而不是两张表:
--   派单 —— 店长/客户给的现场照、参考图,是「要做什么」的证据
--   总结 —— 顾问做完拍的,是「做成什么样」的证据
-- 合成一列存的话,一张图到底是要求还是结果就只能靠上传时间猜。
CREATE TABLE schedule_file(id INTEGER PRIMARY KEY AUTOINCREMENT,
  schedule_id TEXT, kind TEXT, name TEXT, mime TEXT, size INT, path TEXT,
  uploaded_by TEXT, uploaded_at TEXT);
CREATE TABLE ordr(id TEXT PRIMARY KEY, customer_id TEXT, kind TEXT, status TEXT,
  advisor TEXT, shop TEXT, source TEXT, activity TEXT, delivery TEXT,
  -- 这一单是给**谁**做的。原来没有这个字段,于是
  -- 「超期的量体不许下单」那条规则(12-成长与生命周期.md 第五节)
  -- **执行不了** —— 一个客户名下可以有本人和两个孩子,判不出用谁的尺寸。
  -- 可空:名下多人而定不下来时**留空**,下单校验会报「判不了」——
  -- **判不了不等于可以**,不许挑一个候选顶上。
  wearer_id TEXT,
  amount REAL, payable REAL, created TEXT, updated TEXT,
  prd_status TEXT, goods_amount REAL, freight REAL, received REAL, refund_status TEXT,
  addr TEXT, paid_at TEXT, audit_at TEXT, produced_at TEXT, shipped_at TEXT,
  finished_at TEXT, cancelled_at TEXT, remark TEXT);
CREATE TABLE ordr_item(id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, sku TEXT,
  name TEXT, tag TEXT, price REAL, qty INT,
  spu TEXT, base_amount REAL, custom_amount REAL, total REAL,
  -- 这一**行**是给谁做的。挂在行上不挂在订单上,是因为
  -- **一单可以给不止一个人做**(实测 7 单是两件童款加一件女款,一家三口订同款)。
  -- 挂在订单上只能挑一个填,而挑谁都不对。
  wearer_id TEXT);
CREATE TABLE category(code TEXT PRIMARY KEY, name TEXT, parent TEXT, sort INT, status TEXT);
CREATE TABLE product(spu TEXT PRIMARY KEY, name TEXT, category TEXT, kind TEXT, status TEXT,
  base_price REAL, template TEXT, created TEXT, updated TEXT, cover TEXT,
  tag_price REAL, unit TEXT, gender TEXT, points INT, commission_type TEXT, commission_val REAL,
  on_shelf_at TEXT, remark TEXT, img_main TEXT, img_detail TEXT, img_intro TEXT,
  -- 这个商品用哪个版型。**性别和量体模板都从它派生,不在商品上另填一遍** ——
  -- 补这条边之前,86 个有版型的定制品里 **66 个的量体模板和版型对不上**
  -- (长衫按裙子的口径量)。同一个事实两个来源,必然漂。
  -- 可空:按名字匹配不上的留空,**不猜** —— 猜错的话用料/工期/量体全跟着错。
  pattern TEXT);
CREATE TABLE sku(code TEXT PRIMARY KEY, spu TEXT, spec TEXT, color TEXT, size TEXT,
  price REAL, stock INT, locked INT, status TEXT,
  collar TEXT, size_no TEXT, spec_code TEXT, weight_kg REAL, volume_m3 REAL,
  points INT, img TEXT);
CREATE TABLE measure_item(code TEXT PRIMARY KEY, name TEXT, unit TEXT, required INT,
  sort INT, status TEXT, note TEXT);
CREATE TABLE measure_tpl(code TEXT PRIMARY KEY, name TEXT, descr TEXT, status TEXT,
  updated_by TEXT, updated TEXT);
CREATE TABLE tpl_item(tpl TEXT, item TEXT, sort INT);
-- 体型特征 —— 「差 >5cm **或有明显体型特征** 即全定制」里的后半句,
-- 之前只是知识库里的一句话,没有任何字段承载它,所以那条规则永远跑不到。
-- 体型特征挂**着装人**,不挂门店档案。
-- 原来挂 customer_id,而一条档案下可能有 3 个人 ——
-- 妈妈的「溜肩」会被算到 3 岁儿子头上,而规则是「有明显体型特征即全定制」,
-- 于是孩子被直接推成全定制:**加价又加工期**。
-- 体型特征和身高胸围一样,是**这个人身上的事**。
CREATE TABLE body_feature(wearer_id TEXT, feature TEXT, note TEXT, recorded_by TEXT, ts TEXT);
-- ── 账户 ────────────────────────────────────────────────────────────────
-- **账户在门店档案之上。** 一个人 = 一个账户;门店档案(customer)可以有好几条 ——
-- 在不同店建过档就是两条,这正是「客户合并」工单要解决的事。
-- 按手机号建账户,那 16 组「同名 + 同生日 + 同地址 + 同号」的重复档案
-- **天然落进同一个账户**,不需要人去合。
--
-- 身份口径:
--   phone       主标识,唯一,必填 —— 「账户 id 以手机号为主」
--   login_name  自设账号,可空,唯一
--   pwd_*       自设密码。**只存 PBKDF2 哈希 + 每账户独立的盐,绝不存明文**,
--               而且**不允许经工具层访问**(和 truth 表同一条规矩,api._rows 里硬拦)
CREATE TABLE account(
  id TEXT PRIMARY KEY,
  -- A1/A9:**登录凭据**。着装人那个 phone 是**联系方式**,两件事,别合并。
  phone TEXT NOT NULL UNIQUE,
  login_name TEXT UNIQUE, pwd_algo TEXT, pwd_salt TEXT, pwd_hash TEXT,
  status TEXT DEFAULT '正常', created TEXT, last_login TEXT,
  -- 称呼与联系:账户原来没有名字,名字散在门店档案和着装人上 ——
  -- 顾问打开账户第一眼要知道「叫她什么」
  display_name TEXT, contact_pref TEXT, default_addr TEXT, home_shop TEXT,
  -- A8:有且只有一个「本人」着装人。指出来,而不是靠 relation 字符串猜
  self_wearer_id TEXT,
  -- 合规:协议是有版本的 —— **改了条款而没重新取得同意,等于没同意**
  tos_version TEXT, privacy_version TEXT, marketing_consent INT DEFAULT 0,
  -- 「注销」和「数据删除」是两件事,分别记时间
  closed_at TEXT, purge_at TEXT,
  -- 登录安全:没有这个,自设密码那一档等于裸奔
  fail_count INT DEFAULT 0, locked_until TEXT);
-- A6:换号之后旧号仍要能找到人。合并流程写着「手机号取新号」,
-- 不留别名就等于让客户失联 —— 客户拿旧号来问,系统会说查无此人。
CREATE TABLE phone_alias(
  phone TEXT PRIMARY KEY, account_id TEXT, reason TEXT, since TEXT);
-- ── 着装人与家庭 ────────────────────────────────────────────────────────
-- 原来所有身体数据都挂在 customer_id 上,而 customer 是**账号 / 付钱的人**。
-- 妈妈给女儿买汉服时,**付款人、收货人、量体对象是三个不同的人** ——
-- 女儿没有账号,却是唯一一个身体数据有意义的人。所以把两个概念拆开。
CREATE TABLE wearer(
  id TEXT PRIMARY KEY, customer_id TEXT,   -- 建档来源的门店档案(可能有多条)
  account_id TEXT,                         -- **身份绑定在这** —— 一个账户可以有多个着装人
  name TEXT, gender TEXT,                  -- 男 / 女
  birthday TEXT,                           -- **存生日,不存年龄。**
                                           -- 年龄每天在变,存年龄的系统一年后全库都错,
                                           -- 而且错得很安静 —— 不报错,只是所有推算偏一岁。
  relation TEXT,                           -- 本人 / 配偶 / 子 / 女 / 父 / 母
  -- A9:**联系方式**,可空(孩子没手机)、**可重复**(妈妈给全家都留自己的号)。
  -- 和 account.phone 是两件事:那个管「能不能登进来」,这个管「衣服出问题打给谁」。
  phone TEXT,
  parent_a TEXT, parent_b TEXT,            -- 指向同账号下的另两个 wearer,用于靶身高校验
  height REAL,                             -- 成人自报身高(父母身高是靶身高的唯一个体化输入)
  status TEXT DEFAULT '在用', created TEXT);
-- 同意记录 —— 身体数据属于敏感个人信息;不满十四周岁未成年人的个人信息**一律**是。
-- 依《个人信息保护法》,处理敏感个人信息需**单独同意**(第 28 条);
-- 处理不满十四周岁未成年人信息还须**监护人同意**并制定专门规则(第 31 条)。
-- **没有这张表,这个模块不能上线 —— 能跑也不能上。**
CREATE TABLE consent(
  id TEXT PRIMARY KEY, wearer_id TEXT,
  scope TEXT,                              -- 身体数据 / 未成年人 / 营销触达
  granted_by TEXT, relation TEXT,          -- 谁同意的、什么关系(未成年须监护人)
  channel TEXT, granted_at TEXT, revoked_at TEXT);
-- 生长推算留档 —— 存的**不是结果,是当时怎么推的**:
-- 基于哪次量体、用了哪个方法、推到哪天、给了多宽的区间。
-- 事后客户说「你们说能穿到明年」,得查得出当时到底说了什么。
CREATE TABLE growth_forecast(
  id INTEGER PRIMARY KEY AUTOINCREMENT, wearer_id TEXT,
  base_at TEXT, base_height REAL, base_z REAL,
  method TEXT, target_at TEXT,
  pred_height REAL, lo REAL, hi REAL, note TEXT, created TEXT);
-- ── 工坊产能 ──────────────────────────────────────────────────────────
-- staff / schedule 都是**门店侧**的(店长、顾问、客户预约),工坊的师傅原来根本不在库里。
-- 工期推算一直默认「师傅立刻有空」—— 那是最乐观的假设,而定制业最常见的延期原因
-- 恰恰是**排不上**,不是做得慢。
CREATE TABLE artisan(
  no TEXT PRIMARY KEY, name TEXT, trade TEXT,      -- 工种:织造/印染/刺绣/缝制
  skills TEXT,                                     -- 会哪几种工艺(KF 编码,逗号分隔)
  day_rate REAL DEFAULT 1.0,                       -- 日产能:一天出几个工日
  wip_limit INT DEFAULT 2,                         -- 同时能接几件(在制上限)
  workshop TEXT, status TEXT, note TEXT);
-- 已排上的活。**未完成的工单占着未来的产能** —— 新单要排在它们后面
CREATE TABLE workorder(
  id TEXT PRIMARY KEY, artisan TEXT, craft TEXT, ref TEXT,
  workdays REAL, start_date TEXT, due_date TEXT, status TEXT, note TEXT);
-- wearer_id:衣服穿在谁身上。**在已有表上加一个维度,不另起一套量体表** ——
-- 另起一套的代价是两份量体数据迟早打架,而且 fitting.py 得跟着分叉。
-- 老记录一律指向该账号的「本人」着装人,所以历史数据不用改口径。
CREATE TABLE measure_rec(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id TEXT, tpl TEXT,
  item TEXT, value REAL, measured_by TEXT, measured_at TEXT, method TEXT DEFAULT '到店',
  wearer_id TEXT,
  -- 这批量体是**哪次上门/接待量的**(schedule.id)。可空 —— 历史数据没有这条边。
  -- 补它的理由:原来只有客户号和时间戳,要问「这次上门量了什么」只能拿时间去猜。
  -- 同一个客户量过三次(2 月到店、6 月到店、9 月上门),猜就会猜错 —— 我自己就猜错过一次:
  -- 拿「最新的模板分组」当成这次的,取到了 2 月那批,于是「时间先后」这条验证误报。
  -- **靠时间戳连起来的两张表,平时和真有外键长得一模一样,直到有人量了第二次。**
  --
  -- ⚠️ 叫 schedule_id 不叫 task_id:**库里有两个都叫「任务」的东西** ——
  -- `schedule` 是日程任务(派给顾问的活),`task` 是人工工单(退款/合并/判责)。
  -- 第一版叫 task_id,悬空引用检查按列名猜表、去找 `task`,当场报 15 条对不上。
  -- 检查抓对了「有条边对不上」,但**推错了指向哪儿** —— 而它推错的方式
  -- 恰恰是我加列时的方式:**看名字**。命名撞车的代价在这儿现形。
  schedule_id TEXT,
  -- 08-量体与版型.md 第四节:「每次量体必须记下三件事,**缺一件就等于没量**」——
  -- ①数值+单位 ②**量体条件** ③量体人+时间。前后两件早就有了,唯独缺第二件,
  -- 而文档专门写着它「最常漏」:同一个人穿厚内搭和不穿,胸围差 3–4cm,
  -- **没记条件的尺寸,返修时无法判断是量错了还是穿法变了**,争议只能靠嗓门解决。
  cond_inner TEXT,   -- 内搭:无 / 薄 / 厚
  cond_shoe TEXT,    -- 鞋:赤足 / 平底 / 高跟(影响身高与裙长)
  cond_breath TEXT); -- 呼吸状态:平静呼气 / 吸气
CREATE TABLE content(code TEXT PRIMARY KEY, title TEXT, kind TEXT, status TEXT,
  channel TEXT, author TEXT, published TEXT, views INT);
CREATE TABLE activity(code TEXT PRIMARY KEY, name TEXT, kind TEXT, status TEXT,
  start_d TEXT, end_d TEXT, shop TEXT, budget REAL, signup INT, orders INT, created TEXT);
CREATE TABLE activity_cost(id INTEGER PRIMARY KEY AUTOINCREMENT, activity TEXT, item TEXT,
  amount REAL, note TEXT, created_by TEXT, created TEXT);
CREATE TABLE invite_code(code TEXT PRIMARY KEY, batch TEXT, activity TEXT, status TEXT,
  used_by TEXT, used_at TEXT, created TEXT);
CREATE TABLE page(code TEXT PRIMARY KEY, name TEXT, channel TEXT, status TEXT,
  updated_by TEXT, updated TEXT);
CREATE TABLE page_block(id INTEGER PRIMARY KEY AUTOINCREMENT, page TEXT, sort INT,
  kind TEXT, title TEXT, cfg TEXT);
CREATE TABLE sys_code(code TEXT PRIMARY KEY, category TEXT, name TEXT, val TEXT,
  sort INT, status TEXT, note TEXT);
CREATE TABLE op_log(
  -- 操作日志。**原来这张表是 server.py 导入时的副作用建的**(ensure_oplog),
  -- 于是「刚 seed 完的库」里没有它 —— write_check 先拷副本再 import server,
  -- 副本就缺这张表,报 `no such table: op_log`,而且**只有 reseed 后第一次会红**。
  -- 业务表不该靠 import 的副作用存在。ensure_oplog 留着当兜底,但源头在这儿。
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, machine TEXT,
  target TEXT, frm TEXT, too TEXT, allowed INT, code TEXT, reason TEXT, ctx TEXT);
CREATE TABLE download_task(id TEXT PRIMARY KEY, kind TEXT, filters TEXT, status TEXT,
  rows_n INT, size_kb INT, created_by TEXT, created TEXT, expire_at TEXT);
CREATE TABLE level_cfg(code TEXT PRIMARY KEY, name TEXT, amount REAL, orders INT,
  sort INT, status TEXT, note TEXT, need_points INT, point_rule TEXT);
CREATE TABLE tag(code TEXT PRIMARY KEY, name TEXT, grp TEXT, status TEXT, n INT, updated TEXT);
CREATE TABLE approval(id TEXT PRIMARY KEY, kind TEXT, target TEXT, payload TEXT,
  status TEXT, applied_by TEXT, applied_at TEXT, decided_by TEXT, decided_at TEXT, note TEXT);
CREATE TABLE aftersale(id TEXT PRIMARY KEY, kind TEXT, order_id TEXT, customer_id TEXT,
  status TEXT, reason TEXT, amount REAL, shop TEXT, advisor TEXT, created TEXT, updated TEXT,
  ext_system TEXT, synced_at TEXT);
-- 交付告知签收 —— 09-养护与售后.md 第三节写着「交付时必须书面告知的六条」,
-- 第五节的返修判定里,**特性类(色差/掉色/勾丝)是否书面告知,直接决定有责无责**:
--   已书面告知 → 无责,解释 + 提供保养服务
--   **未**书面告知 → 我方,让步处理
-- 这条判据原来在文档里写着,但**库里没有任何字段承载它**,所以那条规则永远跑不到。
-- 和「体型特征」当初的情况一模一样。
CREATE TABLE delivery_notice(
  order_id TEXT PRIMARY KEY, items TEXT,
  signed_at TEXT, advisor TEXT, channel TEXT);
CREATE TABLE maintain(id TEXT PRIMARY KEY, order_id TEXT, customer_id TEXT, item TEXT,
  status TEXT, issue TEXT, shop TEXT, advisor TEXT, created TEXT, updated TEXT,
  ext_system TEXT, synced_at TEXT);
CREATE TABLE stock_log(id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT, spu TEXT,
  kind TEXT, delta INT, before_n INT, after_n INT, ref TEXT, operator TEXT, ts TEXT, note TEXT);
CREATE TABLE craft(code TEXT PRIMARY KEY, name TEXT, cat TEXT, alias TEXT,
  brief TEXT, detail TEXT, fit TEXT, lead_days TEXT, cost_level TEXT,
  src_type TEXT, src_url TEXT, src_name TEXT);
CREATE TABLE craft_combo(craft TEXT, material TEXT, verdict TEXT, reason TEXT, src_type TEXT, rule TEXT);
-- ── 四大库之三、之四:版型库 与 BOM 库 ──
-- 款式库 = product / category,工艺库 = craft + craft_combo(已有);
-- 版型库回答「怎么裁」,BOM 库回答「用多少料、多少钱、多久备齐」。
-- 两张主表都不手写,由 knowledge/10、11 两个 md 推出来。
CREATE TABLE pattern(code TEXT PRIMARY KEY, name TEXT, xz TEXT, gender TEXT, tpl TEXT,
  pieces INT, fabric_base REAL, fabric_step REAL, sizes TEXT, difficulty TEXT, src_type TEXT);
CREATE TABLE pattern_piece(pattern TEXT, name TEXT, qty INT, note TEXT);
-- 推档结果:每个版型 × 每个尺码 × 每个部位。基码和档差在 md 里,这张表是算出来的
CREATE TABLE size_spec(pattern TEXT, size TEXT, item TEXT, value REAL);
-- 主料行的 name 从 craft 表取,ref_craft 指回去 —— 面料名不在物料表里存第二遍
CREATE TABLE material(code TEXT PRIMARY KEY, name TEXT, cat TEXT, spec TEXT, width_cm REAL,
  unit TEXT, price REAL, loss_rate REAL, lead_days INT, ref_craft TEXT, src_type TEXT,
  -- 现货米数。**没有这个字段,工期推算那条「改用现货面料可压缩 20 天」就是空话** ——
  -- 系统根本不知道哪些面料有现货。越贵的料现货越少,这是真实的:压着钱的东西没人多囤。
  stock_qty REAL DEFAULT 0);
CREATE TABLE pattern_bom(pattern TEXT, material TEXT, qty_base REAL, qty_step REAL, unit TEXT, note TEXT);
CREATE TABLE craft_bom(craft TEXT, material TEXT, qty REAL, unit TEXT, note TEXT);
CREATE TABLE kb_table(topic TEXT, head TEXT, rows TEXT, src_file TEXT);
CREATE TABLE product_custom(spu TEXT PRIMARY KEY, xz TEXT, mt_opts TEXT, kf_opts TEXT,
  lead_days TEXT, note TEXT);
CREATE TABLE scheme(id TEXT PRIMARY KEY, customer_id TEXT, name TEXT, status TEXT,
  -- ⚠️ 下面这四个字段**原来存的是名字**(「明制立领长衫」「云锦」),
  -- 而名字一改,所有历史方案的引用**当场断掉而且悄无声息**。
  -- 现在存**编码**,名字要显示时去主数据取 —— 见 `knowledge/scheme_ref.py`。
  -- 这和「订单靠活动名连活动」是同一个病,前几天刚修过一次。
  xz TEXT,        -- 形制编码 XZ**(不是形制名)
  mt TEXT,        -- 主料编码 MT**(不是面料名)
  kf TEXT,        -- 工艺编码,逗号分隔(不是工艺名)
  color TEXT, ps TEXT,
  -- **版型接进来。** 方案里选的是形制,而真正决定
  -- 用料多少 / 量体量哪些 / 能不能做 的是**版型** ——
  -- 一个形制下常有好几个版型(标准/加长/改良通勤、男款/女款),
  -- 报价和排产都得落到具体那一个。原来这条边不存在,
  -- 于是方案报得出「明制立领长衫」,报不出「用多少米料」。
  pattern TEXT,   -- 版型编码 PT**
  advisor TEXT, note TEXT, created TEXT, updated TEXT);
CREATE TABLE truth(case_id TEXT PRIMARY KEY, breakpoint TEXT, root_cause TEXT,
  expected_action TEXT, expected_evidence TEXT, note TEXT,
  -- 来源:建库标注 = 上线前人工写的;人工改判 = 上线后值班同学否掉智能体时回流进来的。
  -- 分开记是因为回流条目**没有第二个人复核过**,回归时要能单独看它们的通过率 ——
  -- 否则一个判错的人工裁决会悄悄变成"标准答案"。
  src TEXT DEFAULT '建库标注');
"""

# ── 退款失败的六类真因(BP-01)────────────────────────────
REFUND_CASES=[
 ("渠道超时但实际已退","支付平台三次均返回 TIMEOUT,但正向查询显示退款已成功",
  "不得再次发起退款;应以支付平台查询结果为准,将押金置为已退并补记流水",
  "payment_flow 中存在方向为 out 且状态为 success 的记录",
  [("TIMEOUT","渠道响应超时"),("TIMEOUT","渠道响应超时"),("TIMEOUT","渠道响应超时")], True),
 ("退款金额超过可退额","请求退款金额大于原支付金额",
  "驳回并按原支付金额重新发起;需财务确认差额来源",
  "req_amount 大于 payment_flow 中 in 方向的 amount",
  [("AMOUNT_EXCEED","退款金额超过原交易金额")]*3, False),
 ("原支付渠道已注销","客户原支付账户已销户,渠道返回 ACCOUNT_CLOSED",
  "转财务人工处理,走线下退款并留痕;不得重试",
  "resp_code 为 ACCOUNT_CLOSED",
  [("ACCOUNT_CLOSED","收款账户已注销")]*3, False),
 ("幂等号重复提交","三次重试使用了不同幂等号,存在重复出账风险",
  "立即停止重试并核对是否已出账;后续重试必须复用原幂等号",
  "refund_trace 三条记录的 idem_key 不一致",
  [("DUPLICATE","重复请求")]*3, False),
 ("商户账户余额不足","商户结算账户余额不足以完成退款",
  "通知财务充值后重试;不属于单据问题",
  "resp_code 为 INSUFFICIENT_BALANCE",
  [("INSUFFICIENT_BALANCE","商户账户余额不足")]*3, False),
 ("审批未完成即发起","押金仍处于退款审批中,却已发起退款请求",
  "撤回退款请求,补齐店长复核(单笔≥1000元需财务复核)后重新发起",
  "deposit.status 为退款审批中,但 refund_trace 已有记录",
  [("NOT_APPROVED","审批状态不允许")]*3, False),
]

TODAY="2026-08-31"
from datetime import date, timedelta
T=date(2026,8,31)
# ── 营销活动花名册 ────────────────────────────────────────────────
# **模块级**,因为订单块和活动块都要用它,而订单块在前面。
# 原来活动名硬编在订单块里(`ACT=["品牌文化体验活动",...]`),活动表另写一份 ——
# **同一批活动两个来源**,加一个活动就得改两处,而漏改的那处不会报错。
ACTS = [("AC2601", "品牌文化体验活动", "线上", "进行中", "2026-08-01", "2026-09-30", 128000.0),
        ("AC2602", "春季新品预售",     "线上", "已结束", "2026-03-01", "2026-04-15",  86000.0),
        ("AC2603", "老客转介绍",       "门店", "进行中", "2026-06-01", "2026-12-31",  45000.0),
        ("AC2604", "静安旗舰店周年庆",  "门店", "未开始", "2026-10-01", "2026-10-07",  68000.0),
        ("AC2605", "非遗工艺展联名",    "联名", "进行中", "2026-07-15", "2026-09-15", 210000.0),
        ("AC2606", "会员日专享",       "线上", "已取消", "2026-05-01", "2026-05-07",  32000.0)]

# 门店活动挂哪家店 —— **按名字定,不随机挑**。
# 原来是 `random.choice(SHOPS)`,于是「**静安**旗舰店周年庆」被挂到了杭州湖滨店。
# 名实不符的数据最麻烦:它不报错,只是让每一份按门店汇总的报表都错一点点。
ACT_SHOP = {"AC2603": "SH002 徐汇店", "AC2604": "SH001 静安旗舰店"}


def ago(days): return (T-timedelta(days=days)).isoformat()

# 判定口径的唯一源头在 knowledge/lifecycle.py。
# 这里原来是**一份手抄件**(PRIORITY + match_rules + decide),server.py 里还有另一份。
# 两份都写着同一个优先级列表 —— 同一个事实两个来源,必然漂,而且漂了不报错。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge"))
import lifecycle as _lc
PRIORITY = _lc.PRIORITY

def _days(iso):
    return (T - date.fromisoformat(iso)).days if iso else None

def match_rules(c):
    return _lc.match(dict(c, days_since_first_order=_days(c.get("first_order"))))

def decide(c):
    r = _lc.decide(dict(c, days_since_first_order=_days(c.get("first_order"))))
    return r["系统重算值"], r["命中"]

# ── 员工花名册:**「谁在哪个店」只有这一个来源** ─────────────────────
# 客户的归属顾问、日程的顾问、预约的顾问,全部从这张表派生。
# 原来是另起一个 ADV=["A01 林岚",…] 平铺列表,和门店无关地随机挑 ——
# 结果是静安店的顾问绑着徐汇店的客户。**同一个事实两个来源,必然漂**。
#   (工号, 姓名, 角色, 门店, 顾问编号, 在职状态)
STAFF = [
    ("60000001", "张静静", "店长",   "SH001 静安旗舰店", None,  "启用"),
    ("60000002", "林岚",   "顾问",   "SH001 静安旗舰店", "A01", "启用"),
    ("60000003", "周叙",   "顾问",   "SH001 静安旗舰店", "A02", "启用"),
    ("60000011", "苏彧",   "顾问",   "SH001 静安旗舰店", "A05", "启用"),
    ("60000012", "顾晚",   "顾问",   "SH001 静安旗舰店", "A06", "启用"),
    ("60000013", "白鹭",   "顾问",   "SH001 静安旗舰店", "A07", "启用"),
    # ⚠️ 反例夹具 · 不许「顺手把她改成启用」──────────────────────────
    # 何苓已离职,但她名下还挂着客户。客户来预约时,系统**不能**把单子
    # 派给一个已经走的人 —— 那种单子会安静地躺在一个没人看的账号里,
    # 直到客户打电话来问。这条数据就是用来把这个洞逼出来的。
    ("60000015", "何苓",   "顾问",   "SH001 静安旗舰店", "A09", "停用"),
    ("60000004", "周恒东", "店长",   "SH002 徐汇店",     None,  "启用"),
    ("60000005", "沈砚",   "顾问",   "SH002 徐汇店",     "A03", "启用"),
    ("60000006", "陆微",   "顾问",   "SH002 徐汇店",     "A04", "启用"),
    ("60000007", "李明华", "店长",   "SH003 杭州湖滨店", None,  "启用"),
    ("60000014", "程萦",   "顾问",   "SH003 杭州湖滨店", "A08", "启用"),
    ("60000008", "魏欣新", "总部运营", "",               None,  "启用"),
    ("60000009", "陈曦",   "总部运营", "",               None,  "启用"),
    ("60000010", "何舟",   "财务",   "",                 None,  "启用"),
]


def advisors_of(shop, include_left=False):
    """某个门店的顾问,写成「A01 林岚」这种业务侧显示串。

    include_left=True 才带上离职的 —— 默认不带,因为**能被派单的只有在职的**。
    """
    return [f"{a} {n}" for no, n, ro, sh, a, st in STAFF
            if ro == "顾问" and sh == shop and (include_left or st == "启用")]


def run():
    if os.path.exists(DB): os.remove(DB)
    c=sqlite3.connect(DB); c.executescript(SCHEMA)
    SHOPS=["SH001 静安旗舰店","SH002 徐汇店","SH003 杭州湖滨店"]
    # ADV 平铺列表已删。顾问一律按门店取 —— 见 advisors_of()。
    ADV_BY_SHOP = {sh: advisors_of(sh) for sh in SHOPS}
    def _adv(shop): return random.choice(ADV_BY_SHOP[shop])
    SURN="陈林黄张李王吴刘蔡杨"; GIVEN=["雨桐","知微","砚清","书言","молод","апрель","子衿","望舒","астра","青梧"]
    GIVEN=[g for g in GIVEN if all('一'<=ch<='鿿' for ch in g)]

    # 基础客户 60 人
    def mk(cid,name,idle,ocnt,amt,o12,q12,first,manual=None,mat=None):
        row=dict(id=cid,name=name,order_cnt=ocnt,paid_amount=amt,amount_12m=amt,
                 orders_12m=o12,quarters_12m=q12,first_order=first,idle_days=idle)
        lc,m=decide(row)
        eff = manual if (manual and mat and (T-date.fromisoformat(mat)).days<=30) else lc
        phone=f"13{random.randint(100000000,999999999)}"
        _shop = random.choice(SHOPS)
        # 归属顾问必须是**本店**的 —— 客户在静安店,顾问就不能是徐汇店的人。
        return (cid,name,phone,phone[-4:],_shop,_adv(_shop),eff,
                random.choice(["普通","银卡","金卡"]),first or ago(400),ocnt,amt,ago(idle),
                f"上海市{random.choice('静徐黄浦长宁')}区{random.randint(1,999)}号",
                f"199{random.randint(0,9)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}",0,
                first,o12,q12,amt,idle,"/".join(m),manual,mat)

    cust=[]
    # 60 个常规客户:参数随机,但生命周期一律由规则算出
    for i in range(60):
        idle=random.choice([5,20,45,80,95,140,175,200,300,380,500])
        ocnt=random.randint(0,8); o12=min(ocnt,random.randint(0,6))
        amt=0.0 if ocnt==0 else round(random.uniform(500,42000),2)
        first=None if ocnt==0 else ago(random.randint(10,700))
        cust.append(mk(f"C{10000+i}", random.choice(SURN)+random.choice(GIVEN),
                       idle,ocnt,amt,o12,random.randint(1,4),first))
    c.executemany("INSERT INTO customer(id,name,phone,phone_tail,shop,advisor,lifecycle,level,created,order_cnt,paid_amount,last_interact,addr,birthday,archived,first_order,orders_12m,quarters_12m,amount_12m,idle_days,matched,manual_lc,manual_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", cust)

    # ── A2/A3/A4 专用案例 ─────────────────────────────
    EDGE=[
     ("E-A3-01","互动第 90 天(活跃/休眠边界)",90,3,8000,3,2,ago(300),None,None,"活跃",
      "「90 天内有有效互动=活跃」,第 90 天应含端计入活跃"),
     ("E-A3-02","互动第 91 天(活跃/休眠边界)",91,3,8000,3,2,ago(300),None,None,"休眠",
      "「无互动 91-180 天=休眠」,第 91 天进入休眠"),
     ("E-A3-03","互动第 180 天(休眠/潜在流失边界)",180,3,8000,3,2,ago(400),None,None,"休眠",
      "休眠区间上界含端"),
     ("E-A3-04","互动第 181 天(休眠/潜在流失边界)",181,3,8000,3,2,ago(400),None,None,"潜在流失",
      "潜在流失区间下界含端"),
     ("E-A3-05","互动第 365 天(潜在流失/流失边界)",365,3,8000,3,2,ago(500),None,None,"潜在流失",
      "「超过 365 天=流失」,第 365 天仍属潜在流失"),
     ("E-A3-06","互动第 366 天(潜在流失/流失边界)",366,3,8000,3,2,ago(500),None,None,"流失",
      "第 366 天进入流失"),
     ("E-A3-07","实付 14,999 元(高价值边界)",30,5,14999,5,2,ago(200),None,None,"忠诚",
      "未达 15000,不计高价值;因满 4 单跨两季度而为忠诚"),
     ("E-A3-08","实付 15,000 元(高价值边界)",30,3,15000,3,1,ago(200),None,None,"高价值",
      "恰好满 15000,含端计入高价值"),
     ("E-A3-09","4 单但同一季度(忠诚边界)",30,4,9000,4,1,ago(60),None,None,"活跃",
      "满 4 单但未跨两个季度,不计忠诚"),
     ("E-A2-01","高价值 + 潜在流失同时命中",200,6,30000,6,3,ago(300),None,None,"潜在流失",
      "优先级 潜在流失(2) > 高价值(5),必须取潜在流失"),
     ("E-A2-02","忠诚 + 流失同时命中",400,8,26000,8,4,ago(500),None,None,"流失",
      "优先级 流失(1) 最高,压过忠诚"),
     ("E-A2-03","新客 + 高价值同时命中",10,2,32000,2,1,ago(20),None,None,"高价值",
      "优先级 高价值(5) > 新客(6)"),
     ("E-A4-01","人工调整 15 天前(仍在 30 天窗口内)",200,6,30000,6,3,ago(300),"高价值",ago(15),"高价值",
      "人工结果 30 天内优先,重算值(潜在流失)被抑制"),
     ("E-A4-02","人工调整 35 天前(已超窗)",200,6,30000,6,3,ago(300),"高价值",ago(35),"潜在流失",
      "超过 30 天优先期,以重算值为准"),
    ]
    edge_rows=[]
    for cid,nm,idle,ocnt,amt,o12,q12,first,man,mat,expect,note in EDGE:
        edge_rows.append(mk(cid,nm,idle,ocnt,amt,o12,q12,first,man,mat))
    c.executemany("INSERT INTO customer(id,name,phone,phone_tail,shop,advisor,lifecycle,level,created,order_cnt,paid_amount,last_interact,addr,birthday,archived,first_order,orders_12m,quarters_12m,amount_12m,idle_days,matched,manual_lc,manual_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", edge_rows)

    truths=[]
    for cid,nm,idle,ocnt,amt,o12,q12,first,man,mat,expect,note in EDGE:
        bp="BP-05"
        truths.append((cid,bp,expect,f"生命周期应判定为「{expect}」",note,nm))
    # ── BP-01:24 个退款失败案例(6 类 × 4)───────────────
    n=0
    for cls,(cause,desc,action,evid,traces,已退) in enumerate(REFUND_CASES):
        for k in range(4):
            did=f"D{2000+n}"; cid=cust[n%len(cust)][0]; amt=round(random.choice([500,800,1000,1500,2000,3000]),2)
            status="退款失败" if cause!="审批未完成即发起" else "退款审批中"
            idem=f"IDEM-{did}"
            # ⚠️ **押金必须早于它对应的那次预约。** 预约现在跨 6–8 月
            # (见下面 `_AMON`),押金还钉在 8 月的话,
            # `spec_check` 的 C3「任何记录的时间不得早于它所属对象的创建时间」
            # 当场红 14 条 —— **一头挪了另一头没挪,而两头隔着几百行代码。**
            _m = [6, 6, 7, 7, 7, 8, 8, 8, 8, 8][n % 10]
            _d = 3 + (n * 3) % 25
            day = _d
            # 押金创建日 = 预约前两天 —— **先交押金,再约时间**。
            # 方向搞反的话(押金钉死 8-01、预约挪到 6 月)就是
            # 「预约早于它的押金」,C3 当场红 14 条。
            import datetime as _dt3
            _pre = _dt3.date(2026, _m, _d) - _dt3.timedelta(days=2)
            dstr = _pre.isoformat()
            c.execute("INSERT INTO deposit VALUES(?,?,?,?,?,?,?,?)",
                      (did,cid,f"AP{3000+n}",amt,status,idem,dstr,dstr))
            c.execute("INSERT INTO payment_flow VALUES(?,?,?,?,?,?,?,?)",
                      (f"PF{did}I",did,"in",amt,"微信支付",f"WX{random.randint(10**11,10**12)}","success",dstr+" 10:12"))
            if 已退:
                c.execute("INSERT INTO payment_flow VALUES(?,?,?,?,?,?,?,?)",
                          (f"PF{did}O",did,"out",amt,"微信支付",f"WX{random.randint(10**11,10**12)}","success",f"{dstr} 14:31"))
            req = amt*1.5 if cause=="退款金额超过可退额" else amt
            for a,(code,msg) in enumerate(traces,1):
                ik = f"IDEM-{did}-{a}" if cause=="幂等号重复提交" else idem
                c.execute("INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key) VALUES(?,?,?,?,?,?,?,?)",
                          (did,a,f"{dstr} 14:{20+a*3:02d}","微信支付",round(req,2),code,msg,ik))
            c.execute("INSERT INTO task VALUES(?,?,?,?,?,?)",
                      (f"T{did}","财务人工任务",did,"待处理",f"{dstr} 14:35",None))
            truths.append((did,"BP-01",cause,action,evid,desc))
            n+=1

    # ── BP-02:16 对疑似重复客户(8 同一人 / 8 不同人)────
    for i in range(16):
        same = i<8
        base=cust[i]
        aid=f"C2{1000+i*2}"; bid=f"C2{1000+i*2+1}"
        name=base[1]; phone=base[2]
        if same:
            # 同一人:手机号不同(换号)但生日+地址一致,订单在两店
            p2=f"13{random.randint(100000000,999999999)}"
            rows=[(aid,name,phone,phone[-4:],SHOPS[0],_adv(SHOPS[0]),"活跃","金卡","2025-03-01",3,18000.0,"2026-07-01",base[12],base[13],0,"2025-03-01",3,2,18000.0,60,"活跃/高价值",None,None),
                  (bid,name,p2,p2[-4:],SHOPS[1],_adv(SHOPS[1]),"新客","普通","2026-05-01",1,3200.0,"2026-06-20",base[12],base[13],0,"2026-05-01",1,1,3200.0,72,"活跃",None,None)]
            cause="同一客户跨店重复建档"
            action="建议合并;冲突字段取最近一次经确认的数据(手机号取新号),被合并档案归档保留日志"
            evid="生日与地址完全一致,姓名相同,手机号不同(换号)"
        else:
            # 不同人:同名同姓,生日与地址均不同
            p2=f"13{random.randint(100000000,999999999)}"
            rows=[(aid,name,phone,phone[-4:],SHOPS[0],_adv(SHOPS[0]),"活跃","银卡","2025-06-01",2,9000.0,"2026-07-11",base[12],base[13],0,"2025-06-01",2,2,9000.0,50,"活跃",None,None),
                  (bid,name,p2,p2[-4:],SHOPS[2],_adv(SHOPS[2]),"潜在","普通","2026-04-01",0,0.0,"2026-04-02",
                   f"杭州市西湖区{random.randint(1,999)}号",f"198{random.randint(0,9)}-0{random.randint(1,9)}-1{random.randint(0,9)}",0,None,0,0,0.0,150,"潜在",None,None)]
            cause="同名不同人"
            action="不合并;建议在两条档案上互相标注已核验非同一人,避免反复进入队列"
            evid="生日不同、地址城市不同、手机号不同,仅姓名相同"
        c.executemany("INSERT INTO customer(id,name,phone,phone_tail,shop,advisor,lifecycle,level,created,order_cnt,paid_amount,last_interact,addr,birthday,archived,first_order,orders_12m,quarters_12m,amount_12m,idle_days,matched,manual_lc,manual_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        case=f"MERGE-{i:02d}"
        c.execute("INSERT INTO task VALUES(?,?,?,?,?,?)",(f"T{case}","客户合并确认",f"{aid}|{bid}","待处理","2026-08-22",None))
        truths.append((case,"BP-02",cause,action,evid,f"{aid} vs {bid}"))

    # ── 预约记录:每个押金对应一条,状态按后台 PRD 6.1 的预约状态机 ──
    APPT_ST=["已预约","已到店","已完成","已取消","已过期","爽约"]
    WAY=["到店量体","上门沟通","电话回电","到店试衣"]
    # 预约/日程/跟进都挂在某个客户身上 —— 门店跟着**客户**走,不再另掷一次骰子。
    # 独立掷骰的后果是:徐汇店客户的预约落在静安店,顾问也成了静安店的人。
    # ⚠️ 反例夹具 · 不许「顺手把他们改绑给在职顾问」──────────────────
    # 给离职的何苓(A09)留三个客户。**离职不会把客户一起带走** ——
    # 现实里人走了,他名下的客户还在,还会来预约。这三条就是用来检验:
    # 他们来预约时,单子是掉进待分配池(对),还是照样派给何苓(错)。
    # 挑**固定的三个**而不是随机三个 —— 随机的夹具下次重建就换了人,
    # 测试挂了你分不清是代码坏了还是夹具变了。
    _LEFT = [r[0] for r in c.execute(
        "SELECT id FROM customer WHERE shop='SH001 静安旗舰店' ORDER BY id").fetchall()[:3]]
    for _cid in _LEFT:
        c.execute("UPDATE customer SET advisor='A09 何苓' WHERE id=?", (_cid,))

    CSHOP = {r[0]: r[1] for r in c.execute("SELECT id,shop FROM customer").fetchall()}
    def _shop_of(cid): return CSHOP.get(cid) or SHOPS[0]
    def _adv_of(cid):  return _adv(_shop_of(cid))
    def _adv_any():    return random.choice(sum(ADV_BY_SHOP.values(), []))

    deps=[dict(r) for r in c.execute("SELECT id,customer_id,appt_id,amount,status FROM deposit")] if False else \
         [{"id":r[0],"customer_id":r[1],"appt_id":r[2],"amount":r[3],"status":r[4]}
          for r in c.execute("SELECT id,customer_id,appt_id,amount,status FROM deposit")]
    # 预约同样要跨月 —— 理由见下面日程那段的注释:
    # **一条只在「我这台机器的库」上成立的检查,等于没有这条检查。**
    # **和押金用同一个序号**,否则押金在 8 月而预约在 6 月,C3 当场红。
    _AMON = [6, 6, 7, 7, 7, 8, 8, 8, 8, 8]
    for i,d in enumerate(deps):
        st = "已取消" if d["status"] in ("退款失败","退款审批中") else APPT_ST[i%6]
        _n = int(d["id"][1:]) - 2000 if d["id"][1:].isdigit() else i
        mon = _AMON[_n % len(_AMON)]; day = 3 + (_n * 3) % 25
        c.execute("INSERT INTO appointment VALUES(?,?,?,?,?,?,?,?,?)",
          (d["appt_id"], d["customer_id"], _shop_of(d["customer_id"]), _adv_of(d["customer_id"]),
           f"2026-{mon:02d}-{day:02d} {9+i%8:02d}:30",
           f"2026-{mon:02d}-{day:02d} {10+i%8:02d}:30",
           st, d["id"],
           f"2026-{mon:02d}-{day:02d} {9+i%8:02d}:28" if st in ("已到店","已完成") else None))
        c.execute("INSERT INTO followup VALUES(?,?,?,?,?,?,?)",
          (f"F{d['appt_id']}", d["customer_id"], d["appt_id"],
           f"2026-{mon:02d}-{day:02d} 09:10",
           random.choice(["电话","微信","到店"]),
           random.choice(["客户确认到店时间","客户询问面料选项","客户要求改期","客户未接听,留言"]),
           _adv_of(d["customer_id"])))
    # 另建 20 条不带押金的预约
    for i in range(20):
        aid=f"AP{4000+i}"; mon=_AMON[(i+3) % len(_AMON)]; day=3+(i*3)%25
        c.execute("INSERT INTO appointment VALUES(?,?,?,?,?,?,?,?,?)",
          (aid, cust[i%len(cust)][0], _shop_of(cust[i%len(cust)][0]), _adv_of(cust[i%len(cust)][0]),
           f"2026-{mon:02d}-{day:02d} {10+i%7:02d}:00",
           f"2026-{mon:02d}-{day:02d} {11+i%7:02d}:00",
           APPT_ST[i%6], None, None))
    # ── 店铺(后台 PRD 6.1 店铺状态机:有效 ⇄ 无效)──
    SHOPDATA=[("SH001","静安旗舰店","有效","张静静","021-6200-1001","上海市静安区","上海市静安区南京西路 1266 号 3F"),
              ("SH002","徐汇店","有效","周恒东","021-6400-2002","上海市徐汇区","上海市徐汇区淮海中路 1010 号 2F"),
              ("SH003","杭州湖滨店","无效","李明华","0571-8700-3003","浙江省杭州市","杭州市上城区湖滨路 88 号 1F")]
    for code,nm,st,mg,ph,pv,ad in SHOPDATA:
        c.execute("INSERT INTO shop VALUES(?,?,?,?,?,?,?,?)",(code,nm,st,mg,ph,pv,ad,"2026-08-20 10:12"))

    # ── 员工与角色(PRD 第 8 章:按角色做数据权限控制)──
    # 花名册在模块级(见文件上方 STAFF)—— 这里**不再抄一份**。
    # 抄一份的后果不是「两个列表不一样」,而是「客户绑的顾问库里查无此人」:
    # 上面按花名册给客户绑了 A05 苏彧,这里没插他,自动派单就一路静默失败。
    for no, nm, ro, sh, adv, stt in STAFF:
        # **显式写列名。** 原来是 `INSERT INTO staff VALUES(?,?,?,?,?,?,?)` ——
        # 按位置写,给表加一列就当场断,而且报错信息("14 columns but 7 values")
        # 完全指不到「你刚加了列」这个真因。
        c.execute("INSERT INTO staff(no,name,role,shop,status,adv_code,updated_by,updated) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (no, nm, ro, sh, stt, adv, "60000008",
                   "2026-08-2%d 1%d:16" % (random.randint(0, 9), random.randint(0, 9))))


# ── 日程任务(后台 PRD 6.1:有效 → 完结;有效 → 取消/无效)──
    # 类型清单**从 tasktypes 来**,种子里不再自己写一份 ——
    # 写两份的结果是种子造出界面上认不出的类型,而认不出会被当成新的一类。
    import tasktypes as _tt
    STYPE = ["预约到店", "电话回电", "订单跟踪", "日常运维"]
    assert all(_tt.info(t) for t in STYPE), "种子用了 tasktypes 里没有的类型"
    SST=["有效","有效","有效","完结","完结","取消","无效"]
    # ⚠️ **日程要跨月。** 原来 28 条全排在 8 月的 7 天里
    # (`day=14+(i%7)`),于是两条检查在**新灌的库上直接挂**:
    #   · 月度复盘的「改一个月的数据不影响别的月」—— 只有一个月,验不了
    #   · 预约漏斗的「给了起始日之后人数变少」—— 全在一个月,筛不掉任何东西
    # 它们在我这台机器上是绿的,因为库里还有 `run_journey` 造的跨月数据。
    #
    # **一条只在「我这台机器的库」上成立的检查,等于没有这条检查** ——
    # 别人 clone 下来跑一次 seed.py,它当场就红,而红的理由和他做的事无关。
    # 摊到 5–8 月,月份分布也更像真的(近月多、远月少)。
    _MON = [5, 6, 6, 7, 7, 7, 8, 8, 8, 8]
    for i in range(28):
        mon = _MON[i % len(_MON)]
        day = 3 + (i * 3) % 25
        st=SST[i%7]
        c.execute("INSERT INTO schedule(id,type,advisor,customer_id,start_ts,end_ts,status,summary,cancel_reason,shop) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (f"SC{7000+i}", STYPE[i%4], _adv_of(cust[i%len(cust)][0]), cust[i%len(cust)][0],
           f"2026-{mon:02d}-{day:02d} {9+i%9:02d}:00",
           f"2026-{mon:02d}-{day:02d} {10+i%9:02d}:00",
           st, "已完成服务并记录结果" if st=="完结" else None,
           "客户改期" if st=="取消" else None, _shop_of(cust[i%len(cust)][0])))
    # 把历史日程的 advisor(A0x 姓名)对到工号上。
    # **这是一次性迁移** —— 以后新排的任务直接写工号,不再靠名字连。
    _name2no = {r[0]: r[1] for r in c.execute("SELECT name,no FROM staff").fetchall()}
    for _sc in c.execute("SELECT id,advisor FROM schedule").fetchall():
        _nm = (_sc[1] or "").split(" ", 1)[-1]
        if _nm in _name2no:
            c.execute("UPDATE schedule SET assignee_no=? WHERE id=?", (_name2no[_nm], _sc[0]))

    # ── 品类(树形两级)──
    # 三级类目 —— 设计稿「商品库-新建商品」是三个级联下拉,详情页写作「类目一-类目二-类目三」
    CATS=[("C01","女装",None,1),
            ("C0101","上装","C01",1),
              ("C010101","襦 / 衫","C0101",1),("C010102","袄","C0101",2),
              ("C010103","褙子","C0101",3),("C010104","半臂","C0101",4),
            ("C0102","裙装","C01",2),
              ("C010201","马面裙","C0102",1),("C010202","百迭裙","C0102",2),
              ("C010203","齐胸裙","C0102",3),
            ("C0103","外套","C01",3),
              ("C010301","大袖衫","C0103",1),("C010302","长衫 / 长袄","C0103",2),
          ("C02","男装",None,2),
            ("C0201","上装","C02",1),
              ("C020101","圆领袍","C0201",1),("C020102","道袍","C0201",2),
          ("C03","童装",None,3),
            ("C0301","成套","C03",1),
              ("C030101","襦裙套装","C0301",1),("C030102","圆领袍","C0301",2),
          ("C04","配饰",None,4),
            ("C0401","头饰","C04",1),
              ("C040101","簪钗","C0401",1),("C040102","冠 / 额饰","C0401",2),
            ("C0402","腰饰","C04",2),
              ("C040201","腰封 / 腰带","C0402",1),("C040202","宫绦 / 玉佩","C0402",2),
              ("C040203","香囊 / 荷包","C0402",3),
            ("C0403","颈肩饰","C04",3),
              ("C040301","云肩","C0403",1),("C040302","璎珞 / 项圈","C0403",2),
              ("C040303","披帛","C0403",3),
            ("C0404","鞋履","C04",4),
              ("C040401","绣鞋","C0404",1),("C040402","袜 / 其他","C0404",2),
          ("C05","面料部件",None,5),
            ("C0501","面料","C05",1),
              ("C050101","真丝素织","C0501",1),("C050102","锦缎","C0501",2),
              ("C050103","棉麻 / 化纤","C0501",3),
            ("C0502","绣片","C05",2),
              ("C050201","云肩绣片","C0502",1),("C050202","襕边 / 袖缘绣片","C0502",2),
            ("C0503","辅料","C05",3),
              ("C050301","盘扣","C0503",1),("C050302","滚边 / 内衬","C0503",2),
          # ── 西式 / 非汉服 ────────────────────────────────────────
          # 2026-09-13 业务拍板:那件西装(Highbridge Nailhead 海军蓝套装)
          # 原来挂在 C020101 男装·圆领袍下面,于是它一直出现在
          # 「待补版型的成衣」清单里 —— **而它压根不该有汉服形制**。
          # 顶级品类是 `顶级品类()` 判「要不要版型」的依据
          # (只有 女装/男装/童装 算成衣),所以移到新的顶级品类下面,
          # 它就自动不再被要求挂版型,**也不用为它编一个汉服形制**。
          ("C06","西式 / 非汉服",None,6),
            ("C0601","西装","C06",1)]
    for code,nm,pa,so in CATS:
        c.execute("INSERT INTO category VALUES(?,?,?,?,?)",(code,nm,pa,so,"启用"))

    # 知识库必须在商品之前灌 —— 定制品的可选项要现场查 craft_combo 过滤,
    # 表是空的时候过滤器什么都不做,而且**不报错**(踩过:42 个商品全部"通过"了校验)。
    # 工艺知识不在这里手写 —— 由 knowledge/*.md 解析而来,md 是唯一源头。
    # 存两遍一定会漂移,所以这里只负责把解析结果写进表。
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge"))
    import kb as _kb
    CRAFTS = _kb.load()

    for row in CRAFTS: c.execute("INSERT INTO craft VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",row)
    # 决策表:顾问问的多是「客户说 X 我推什么」,这类答案在 md 里是表格不是条目
    for topic,head,rws,fn in _kb.tables():
        c.execute("INSERT INTO kb_table VALUES(?,?,?,?)",
                  (topic,json.dumps(head,ensure_ascii=False),json.dumps(rws,ensure_ascii=False),fn))

    # ── 组合约束矩阵(工艺 × 材质)—— 21 × 13 = 273 格 ────────────────
    # 不手写 273 条。属性表和 R1–R13 规则都在 06-相容矩阵.md 里,
    # derive_combo.py 只负责执行它们 —— md 仍是唯一源头,改 md 就改了全表。
    # 每格带 rule:人工确认 / R2 / R11 …,结论可追到依据,不可追的结论不该给客户。
    import derive_combo as _dc
    for a,b,v,r,rule in _dc.derive():
        c.execute("INSERT INTO craft_combo VALUES(?,?,?,?,'demo',?)",(a,b,v,r,rule))

    # ── 版型库与 BOM 库 —— 同样由 md 推,md 是唯一源头 ──────────────────
    import derive_pattern as _dp
    _names = {r[0]: r[1] for r in c.execute("SELECT code,name FROM craft")}
    for x in _dp.patterns():
        c.execute("INSERT INTO pattern VALUES(?,?,?,?,?,?,?,?,?,?,'demo')",
                  (x["code"], x["name"], x["xz"], x["gender"], x["tpl"], x["pieces"],
                   x["fabric_base"], x["fabric_step"], ",".join(x["sizes"]), x["difficulty"]))
    for x in _dp.pieces():
        c.execute("INSERT INTO pattern_piece VALUES(?,?,?,?)",
                  (x["pattern"], x["name"], x["qty"], x["note"]))
    for row in _dp.size_specs():
        c.execute("INSERT INTO size_spec VALUES(?,?,?,?)", row)
    for m in _dp.materials(_names):
        # 现货量与单价反相关:¥45 的棉麻可以囤几百米,¥1800 的云锦基本不囤 ——
        # 压着钱的东西没人多备。这条规律让「有没有现货」这个问题有真实的答案分布。
        pr = m["price"] or 1
        base = 400 if pr < 60 else 220 if pr < 150 else 90 if pr < 300 else 30 if pr < 700 else 0
        qty = 0.0 if base == 0 and (_dp.materials(_names).index(m) % 3) else round(
            base * (0.4 + (hash(m["code"]) % 100) / 100), 1)
        c.execute("INSERT INTO material VALUES(?,?,?,?,?,?,?,?,?,?,'demo',?)",
                  (m["code"], m["name"], m["cat"], m["spec"], m["width_cm"], m["unit"],
                   m["price"], m["loss"], m["lead"], m["ref_craft"], qty))
    for b in _dp.pattern_bom():
        c.execute("INSERT INTO pattern_bom VALUES(?,?,?,?,?,?)",
                  (b["pattern"], b["material"], b["qty_base"], b["qty_step"], b["unit"], b["note"]))
    for b in _dp.craft_bom():
        c.execute("INSERT INTO craft_bom VALUES(?,?,?,?,?)",
                  (b["craft"], b["material"], b["qty"], b["unit"], b["note"]))

    # ── 会员信息(设计稿「客户详情」的字段)────────────────────────────
    OCC=["室内设计师","中学教师","注册会计师","三甲医院医师","自由摄影师","品牌运营",
         "律师","软件工程师","茶艺师","大学讲师","公务员","民宿主理人"]
    INC=["10w 以下","10w-20w","20w-30w","30w-50w","50w 以上","不愿透露"]
    CAR=["福特蒙迪欧-沪B·UH123","比亚迪汉-沪A·L2K88","无","特斯拉Model Y-浙A·D77Q1",
         "本田CR-V-苏E·M0J52","蔚来ES6-沪C·P3X09","无","大众途观-沪B·K8T21"]
    PROV=[("上海市","上海市","静安区"),("上海市","上海市","徐汇区"),("浙江省","杭州市","西湖区"),
          ("江苏省","苏州市","姑苏区"),("河北省","衡水市","武邑县"),("广东省","广州市","越秀区"),
          ("北京市","北京市","朝阳区"),("四川省","成都市","锦江区")]
    REM=["偏好素雅低饱和,忌大面积撞色","婚期 10 月,需倒推工期","对香云纱气味敏感,已书面告知",
         "有两次远程量体记录,公差按合同约定","习惯微信沟通,电话常不接",None,None,None]
    allc=[r[0] for r in c.execute("SELECT id FROM customer ORDER BY id")]
    # D1:**地址串必须和省市一致**。原来 addr 一律生成成「上海市…」,
    # 而 province/city 另外按下标分配 —— 于是出现「浙江省杭州市」的人住在「上海市浦区」,
    # 全库 21 对「同地址串却不同省市」。**同一个事实两个来源,必然漂。**
    # 改成:PROV 是唯一来源,地址串跟着它生成,只保留原来的门牌号。
    import re as _re
    for n,cid in enumerate(allc):
        pv,ct,ds = PROV[n % len(PROV)]
        _old = c.execute("SELECT addr FROM customer WHERE id=?", (cid,)).fetchone()[0] or ""
        _no = (_re.search(r"\d+号.*$", _old) or [""])[0] if _re.search(r"\d+号.*$", _old) else "1号"
        _addr = f"{pv}{'' if ct == pv else ct}{ds}{_no}"
        c.execute("UPDATE customer SET addr=? WHERE id=?", (_addr, cid))
        c.execute("""UPDATE customer SET gender=?,email=?,wechat=?,occupation=?,income=?,car=?,
                     province=?,city=?,district=?,inviter=?,points=?,remark=? WHERE id=?""",
                  ("女" if n % 5 else "男",
                   f"{cid.lower()}@163.com", f"wx_{cid.lower()}",
                   OCC[n % len(OCC)], INC[n % len(INC)], CAR[n % len(CAR)],
                   pv, ct, ds,
                   allc[(n*7+3) % len(allc)] if n % 4 == 0 else None,
                   random.choice([0,120,380,760,1290,2400,5600,12800]),
                   REM[n % len(REM)], cid))

    # ── 修:BP-02「同一人」8 对的身份字段必须一致 ──────────────────────
    # 上面那个 enumerate 按**下标**分配性别和省市区,而一对里的两条 id 是相邻的,
    # 于是同一个人被分成了「男 / 女」「河北衡水 / 广东广州」—— 而 addr 字符串又一样,
    # 数据**自相矛盾**。
    #
    # 这是跑三代对比时被模型抓出来的:V1 和 V3 都判「不同人」,理由是
    # 「性别矛盾、地址字符串相同但省市区不同」—— **它们的推理是对的,是数据错了**。
    # 而 V2 判对是因为规则只看姓名/生日/地址三项,**看得少所以没看到矛盾** ——
    # 那不是优点。
    #
    # 教训:**模型答错时,先检查真值和数据是不是错的。**
    for _i in range(8):
        _a, _b = f"C2{1000+_i*2}", f"C2{1000+_i*2+1}"
        c.execute("""UPDATE customer SET
                       gender=(SELECT gender FROM customer WHERE id=?),
                       province=(SELECT province FROM customer WHERE id=?),
                       city=(SELECT city FROM customer WHERE id=?),
                       district=(SELECT district FROM customer WHERE id=?),
                       -- D1:**省市和地址串必须一起搬**。只搬省市会留下
                       -- 「河北省的人住在广东省地址」这种矛盾,而真值明写着「地址完全一致」。
                       addr=(SELECT addr FROM customer WHERE id=?)
                     WHERE id=?""", (_a, _a, _a, _a, _a, _b))
    # 「同名不同人」8 对反过来:省市必须真的不同,否则「不同人」这个结论也没依据
    for _i in range(8, 16):
        _a, _b = f"C2{1000+_i*2}", f"C2{1000+_i*2+1}"
        _pa = c.execute("SELECT province,city FROM customer WHERE id=?", (_a,)).fetchone()
        _alt = next(x for x in PROV if x[0] != _pa[0])
        # **改省市就得同时改地址串**,否则 D1 又破了 ——
        # 上一版这里只改省市,留下 2 对「同地址串却不同省市」。
        # 这正是「同一个事实两个来源」的典型:改一处忘一处,而且不报错。
        _oa = c.execute("SELECT addr FROM customer WHERE id=?", (_b,)).fetchone()[0] or "1号"
        _n2 = (_re.search(r"\d+号.*$", _oa) or [None])
        _n2 = _n2[0] if _re.search(r"\d+号.*$", _oa) else "1号"
        c.execute("UPDATE customer SET province=?,city=?,district=?,addr=? WHERE id=?",
                  (*_alt, f"{_alt[0]}{'' if _alt[1]==_alt[0] else _alt[1]}{_alt[2]}{_n2}", _b))

    # 积分流水(设计稿「积分行为」六种)
    BEH=["账户调加","账户调减","积分消费","积分返还","确认款样","完成定购"]
    for n,cid in enumerate(allc):
        bal=int(c.execute("SELECT points FROM customer WHERE id=?",(cid,)).fetchone()[0] or 0)
        run=0
        for k in range(random.randint(0,5)):
            b=BEH[(n+k) % 6]
            amt=random.choice([50,100,200,500,1000])
            delta = -amt if b in ("账户调减","积分消费") else amt
            run += delta
            c.execute("INSERT INTO points_log(customer_id,behavior,delta,balance,ref_id,reason,actor,ts)"
                      " VALUES(?,?,?,?,?,?,?,?)",
                      (cid,b,delta,max(0,bal-run+delta),None,
                       {"账户调加":"人工补发","账户调减":"人工扣减","积分消费":"积分商城兑换",
                        "积分返还":"订单取消返还","确认款样":"定制款样确认奖励",
                        "完成定购":"订单完成奖励"}[b],
                       "魏欣新" if b.startswith("账户") else "系统", ago(k*13+3)))

    # 绑定关系(设计稿 客户详情-绑定关系:邀请人 / 联系人)
    names={r[0]:r[1] for r in c.execute("SELECT id,name FROM customer")}
    for n,cid in enumerate(allc):
        if n % 4 == 0:
            inv=allc[(n*7+3) % len(allc)]
            c.execute("INSERT INTO member_bind(customer_id,kind,target_id,target_name,ts)"
                      " VALUES(?,?,?,?,?)",(cid,"邀请人",inv,names.get(inv),ago(60)))
        if n % 3 == 0:
            ct2=allc[(n*11+5) % len(allc)]
            c.execute("INSERT INTO member_bind(customer_id,kind,target_id,target_name,ts)"
                      " VALUES(?,?,?,?,?)",(cid,"联系人",ct2,names.get(ct2),ago(40)))

    # ── 工坊师傅与在制工单 ────────────────────────────────────────────
    # 工种不是通用劳动力:绣工不会织缂丝,织工也不裁衣服。
    # **织造类一人一机,wip_limit 只能是 1** —— 这不是管理选择,是物理限制。
    ART = [
      ("W0101","沈素心","刺绣","KF03,KF11,KF24,KF34",1.0,2,"苏州绣坊","苏绣主力,兼平绣"),
      ("W0102","顾云舒","刺绣","KF03,KF36,KF34",1.0,2,"苏州绣坊","顾绣,劈丝极细,**不能分工**"),
      ("W0103","唐锦儿","刺绣","KF07,KF11,KF22",1.0,2,"成都绣坊","蜀绣"),
      ("W0104","柳依湘","刺绣","KF08,KF10,KF11",1.0,2,"长沙绣坊","湘绣、打籽"),
      ("W0105","陈婉粤","刺绣","KF09,KF12,KF30",1.0,2,"广州绣坊","粤绣、珠绣,针法最密"),
      ("W0106","苏念金","刺绣","KF04,KF33,KF35",1.0,2,"苏州绣坊","盘金、京绣,重工"),
      ("W0107","方小满","刺绣","KF11,KF22,KF24,KF23",1.2,3,"上海工坊","平绣挑花,手快,预算款主力"),
      ("W0108","何雨眠","刺绣","KF37,KF36",0.8,1,"苏州绣坊","发绣,**一人一稿,换人就变**"),
      ("W0201","罗一机","织造","KF01",1.0,1,"苏州缂丝坊","**缂丝,一台织机只能一个人织**"),
      ("W0202","江云锦","织造","KF02,KF05",1.0,1,"南京云锦坊","**妆花与织金,一人一机**"),
      ("W0203","蒋提花","织造","KF05,KF06",1.0,1,"苏州织造坊","织金、提花"),
      ("W0301","邵青蓝","印染","KF13,KF14,KF15,KF16",1.0,4,"浙南染坊","植物染,按批次,**晾晒占日历天**"),
      ("W0302","黎腊生","印染","KF17,KF27,KF38,KF39",1.0,4,"贵州蜡染坊","蜡染、型糊、灰缬"),
      ("W0303","莨师傅","印染","KF41",1.0,3,"顺德晒莨场","晒莨,**看天吃饭**"),
      ("W0304","文墨行","印染","KF25,KF26",0.9,1,"上海工坊","手绘、描金,**一人一稿**"),
      ("W0401","裁云生","缝制","KF18,KF19,KF20,KF42,KF43",1.0,3,"上海工坊","成衣主力"),
      ("W0402","缝月白","缝制","KF18,KF20,KF28,KF32",1.2,3,"上海工坊","机缝快手"),
      ("W0403","镶三滚","缝制","KF19,KF42,KF44,KF45",0.9,2,"苏州工坊","三镶三滚、堆花"),
      ("W0404","补子安","缝制","KF21,KF31,KF29",1.0,2,"苏州工坊","补子、拼布、盘编"),
      ("W0405","盘扣娘","缝制","KF20,KF29,KF19",1.1,3,"上海工坊","盘扣按颗计,手快"),
      ("W0406","衬里工","缝制","KF18,KF32,KF28",1.0,3,"上海工坊","锁边、压褶"),
    ]
    for no,nm,tr,sk,dr,wl,ws,note in ART:
        c.execute("INSERT INTO artisan VALUES(?,?,?,?,?,?,?,'在职',?)",(no,nm,tr,sk,dr,wl,ws,note))

    # ── 师傅并进 staff:**「工坊排产」这个 agent 角色原来没有对应的登录身份** ──
    #
    # 21 位师傅在 `artisan` 里,工单也按 `W0101` 挂到人了,
    # 而 `prompts.ROLES` 有 `workshop` 角色、11 条规矩 —— **唯独他们登录不了**。
    # 于是那个角色只能被总部运营或店长冒着用,而**师傅看不到自己的活**。
    #
    # 为什么并进 `staff` 而不是给 `artisan` 加登录字段:
    # **`staff` 是「能登录的人」的主表**,而 `artisan` 是工匠的岗位属性
    # (工种、技能、在制上限、日产能)。两张表都放登录字段,
    # 就是「同一个事实两个来源」—— 这个项目为这件事付过很多次学费。
    #
    # `artisan.no`(W0101)保持不变,它是工单上用的编号;
    # `artisan.staff_no` 指向登录身份。**两套编号靠一条边连起来,
    # 而不是靠「都叫一个名字」** —— 「一个人两套编号」那个 bug 就是后者。
    c.execute("ALTER TABLE artisan ADD COLUMN staff_no TEXT")
    for _i5, (no, nm, tr, sk, dr, wl, ws, note) in enumerate(ART):
        _sno = f"7{1000 + _i5:07d}"        # 7 开头,和门店的 6 开头分开
        c.execute("INSERT INTO staff(no,name,role,shop,status,updated_by,updated)"
                  " VALUES(?,?,'工匠',?,'启用','系统',?)",
                  (_sno, nm, ws, T.isoformat()))
        c.execute("UPDATE artisan SET staff_no=? WHERE no=?", (_sno, no))
    # B4:**工单必须指向真实订单**。原来是 `ORD-7001` 这种占位号,53 条没一条对得上,
    # 于是「我的衣服做到哪了」这个定制业最高频的问题根本答不了,产能排期成了孤岛。
    # 一单可以有多道工序(织造/印染/刺绣/缝制),所以多对一是对的。
    # ⚠️ **懒查**:工坊工单在订单之前播种,提前取会拿到空列表 ——
    # 第一版就是这样,53 条 ref 全成了 NULL,而且**不报错**。
    # 「先建的东西引用后建的东西」这类顺序依赖,写成懒查最省心。
    _oc = []
    def _ord_for(i):
        if not _oc:
            _oc.extend(r[0] for r in c.execute(
                "SELECT id FROM ordr WHERE kind='定制品订单' ORDER BY id"))
        return _oc[i % len(_oc)] if _oc else None

    # 在制工单:让「现在排队要等多久」有真实分布 —— 有的师傅空着,有的排到一个月后
    _base = date(2026, 9, 4)
    wo = 0
    for i,(no,nm,tr,sk,dr,wl,ws,note) in enumerate(ART):
        ks = sk.split(",")
        n_job = (i * 7 + 3) % 5          # 0–4 件在制,分布不均才真实
        cur = _base
        for j in range(n_job):
            k = ks[j % len(ks)]
            wd = round(2 + ((i * 13 + j * 7) % 22), 1)
            end = cur + timedelta(days=int(wd / dr) + 1)
            wo += 1
            c.execute("INSERT INTO workorder VALUES(?,?,?,?,?,?,?,'在制',?)",
                      (f"WO{8000+wo}", no, k, _ord_for(wo), wd,
                       cur.isoformat(), end.isoformat(), None))
            cur = end
    # 已完成的历史工单不占产能,但要有,否则看不出「这个师傅一直很忙」
    for i,(no,*_ ) in enumerate(ART[:10]):
        wo += 1
        c.execute("INSERT INTO workorder VALUES(?,?,?,?,?,?,?,'已完成',?)",
                  (f"WO{8000+wo}", no, "KF11", f"ORD-{6900+i}", 6.0,
                   (_base - timedelta(days=40)).isoformat(),
                   (_base - timedelta(days=30)).isoformat(), None))

    # ── 商品(SPU)与 SKU ──
    # 定制品的可选面料 × 可选工艺,**由相容矩阵现场过滤** ——
    # 商品库不能上架一个配置页随后会拒绝的组合,那是自相矛盾。
    _combo = {(a, b): v for a, b, v in
              c.execute("SELECT craft,material,verdict FROM craft_combo")}
    _code = {r[1]: r[0] for r in c.execute("SELECT code,name FROM craft")}
    _combo_rule = {(a, b): u for a, b, u in
                   c.execute("SELECT craft,material,rule FROM craft_combo")}

    def _legal(mts, kfs):
        """去掉会撞上「不可」的面料 —— 保证这个定制品提供的任意组合都能通过校验"""
        keep = []
        for m in mts:
            mc = _code.get(m)
            if any(_combo.get((_code.get(k), mc)) == "不可" for k in kfs): continue
            keep.append(m)
        return keep

    # 标品:名称 / 三级类目 / 售价 / 性别 / 单位 / 颜色 / 尺码 / 领型
    STD = [
      # ⚠️ 品类 C020101(男装·圆领袍)→ C0601(西式)。见上面 CATS 里的说明。
      ("Highbridge Nailhead 海军蓝套装","C0601",2680,"男","套",["藏青","玄色"],["S","M","L","XL"],"圆领"),
      ("「素罗清欢」宋制对襟褙子",     "C010103",1980,"女","件",["月白","竹青","藕荷"],["S","M","L"],"对襟"),
      ("「绫影」宋制百迭裙",           "C010202",1560,"女","条",["竹青","黛"],["S","M","L","XL"],None),
      ("「布衣素心」棉麻交领襦裙",     "C010101", 680,"女","套",["素","赭","竹青"],["M","L","XL"],"交领"),
      ("「云起」醋酸齐胸襦裙(入门)",  "C010203", 980,"女","套",["妃色","月白","缃色"],["S","M","L"],None),
      ("「霜序」提花明制立领长袄",     "C010302",2280,"女","件",["绛","藏青"],["M","L","XL"],"立领"),
      ("「金襕」织金缎马面裙(现货)",  "C010201",3480,"女","条",["胭脂","玄色"],["M","L"],None),
      ("「夏山」香云纱对襟外罩",       "C010301",2960,"女","件",["赭","玄色"],["M","L","XL"],"对襟"),
      ("「烟罗」真丝纱大袖衫",         "C010301",1880,"女","件",["月白","缃色"],["均码"],"直领"),
      ("「玄圭」男装圆领常服袍",       "C020101",2480,"男","件",["藏青","玄色","绛"],["M","L","XL"],"圆领"),
      ("「小满」童款襦裙三件套",       "C030101", 560,"童","套",["妃色","缃色"],["110","120","130","140"],"交领"),
      ("错金鎏银 缠枝发簪",           "C040101", 680,"通用","支",["金","银"],["均码"],None),
      ("点翠嵌珠 步摇",               "C040101",2200,"女","支",["点翠"],["均码"],None),
      ("鎏金花丝 发钗(一对)",        "C040101", 880,"女","对",["金"],["均码"],None),
      ("苏绣双面 玉兰腰封",           "C040201",1280,"女","件",["月白","绛"],["均码"],None),
      ("手工编织 宫绦(带玉佩)",      "C040202", 460,"通用","条",["竹青","绛","玄色"],["均码"],None),
      ("錾刻革带 男装",               "C040201",1180,"男","条",["玄色","赭"],["均码"],None),
      ("盘金绣 云肩(四合如意)",      "C040301",3200,"女","件",["胭脂","玄色"],["均码"],None),
      ("珠串璎珞 项圈",               "C040302",1680,"女","条",["金"],["均码"],None),
      ("真丝绡 披帛(长款)",          "C040303", 520,"女","条",["月白","妃色","缃色"],["均码"],None),
      ("手工绣鞋 平底",               "C040401", 980,"女","双",["绛","玄色"],["35","36","37","38","39"],None),
      ("真丝袜 两双装",               "C040402", 180,"通用","双",["素"],["均码"],None),
      ("真丝香云纱 面料(米白)",      "C050101", 420,"通用","米",["素"],["1米"],None),
      ("宋锦 面料(藏青缠枝)",        "C050102", 860,"通用","米",["藏青"],["1米"],None),
      ("云锦 面料(胭脂缠枝)",        "C050102",1280,"通用","米",["胭脂"],["1米"],None),
      ("真丝绡 面料(月白)",          "C050101", 380,"通用","米",["月白"],["1米"],None),
      ("手工盘金 云肩绣片",           "C050201",1560,"通用","片",["金"],["均码"],None),
      ("苏绣袖缘 绣片(一对)",        "C050202", 640,"通用","对",["月白","妃色"],["均码"],None),
      ("织金襕边 绣片",               "C050202", 880,"通用","条",["金"],["均码"],None),
      ("手工盘扣 花型(六颗装)",      "C050301", 180,"通用","组",["玄色","绛","月白"],["均码"],None),
      ("真丝滚边条 三米装",           "C050302", 120,"通用","卷",["玄色","素","竹青"],["均码"],None),
      ("素绢 内衬(定制裁片)",        "C050302", 260,"通用","片",["素"],["均码"],None),
      ("「琼枝」提花宋制上襦",         "C010101",1180,"女","件",["月白","藕荷","竹青"],["S","M","L"],"交领"),
      ("「秋暝」明制交领短袄",         "C010102",1680,"女","件",["绛","藏青","竹青"],["M","L","XL"],"交领"),
      ("童款圆领袍 男童",             "C030102", 720,"童","件",["藏青","玄色"],["110","120","130"],"圆领"),
      ("手工绣鞋 高帮款",             "C040401",1280,"女","双",["玄色","绛"],["36","37","38","39"],None),
      ("香囊 苏绣款(三只装)",        "C040203", 320,"通用","组",["妃色","竹青","绛"],["均码"],None),
      ("玉佩组佩 腰饰",               "C040202",2680,"通用","组",["玉白"],["均码"],None),
      ("花钿额饰 贴片(十片装)",      "C040102", 160,"女","组",["金","胭脂"],["均码"],None),
      ("发冠 明制男装",               "C040102",1980,"男","顶",["玄色"],["均码"],None),      ('「杭罗清透」宋制对襟短衫','C010101',1280,'女','件',['月白', '竹青', '素'],['S', 'M', 'L', 'XL'],'直领'),
      ('「双宫」明制道袍 男装','C020102',2980,'男','件',['藏青', '玄色', '赭'],['M', 'L', 'XL'],'交领'),
      ('「素缎」明制直裰 男装','C020102',2680,'男','件',['玄色', '藏青'],['M', 'L', 'XL'],'交领'),
      ('「苎麻」明制方领对襟短衫','C010101',580,'女','件',['素', '月白', '缃色'],['S', 'M', 'L', 'XL'],'方领'),
      ('「漳缎」明制披风(秋冬)','C010302',4680,'女','件',['绛', '紫檀', '玄色'],['S', 'M', 'L', 'XL'],'直领'),
      ('「双绉」唐制齐腰襦裙','C010203',1180,'女','套',['妃色', '月白', '藕荷'],['S', 'M', 'L'],None),
      ('「天丝麻」宋制长褙子','C010103',980,'女','件',['竹青', '素', '黛'],['S', 'M', 'L', 'XL'],'直领'),
      ('「暗纹缎」明制立领长袄','C010302',2880,'女','件',['绛', '藏青', '玄色'],['M', 'L', 'XL'],'立领'),
      ('「乔其」唐制大袖披衫','C010301',1580,'女','件',['月白', '缃色', '藕荷'],['均码'],'直领'),
      ('「竹节棉」童款交领襦裙','C030101',460,'童','套',['妃色', '竹青'],['110', '120', '130', '140'],'交领'),
      ('「棉绸」宋制抹胸(内搭)','C010101',280,'女','件',['素', '月白', '妃色'],['S', 'M', 'L'],None),
      ('「杭罗」宋制旋裙','C010202',1380,'女','条',['月白', '竹青', '黛'],['S', 'M', 'L', 'XL'],None),
      ('「素缎」明制褶裙','C010201',1080,'女','条',['绛', '藏青', '玄色'],['S', 'M', 'L', 'XL'],None),
      ('「苎麻」明制比甲','C010104',780,'女','件',['素', '赭', '竹青'],['S', 'M', 'L', 'XL'],None),
      ('「漳缎」明制比甲 长款','C010104',2280,'女','件',['紫檀', '玄色'],['M', 'L', 'XL'],None),
      ('「双宫」宋制圆领襕衫','C020101',3180,'男','件',['素', '月白'],['M', 'L', 'XL'],'圆领'),
      ('「暗纹」唐制圆领缺胯袍','C020101',2680,'男','件',['藏青', '赭'],['M', 'L', 'XL'],'圆领'),
      ('「素缎」明制曳撒 男装','C020102',3880,'男','件',['玄色', '绛'],['M', 'L', 'XL'],'圆领'),
      ('「杭罗」唐制交领襦裙','C010203',1480,'女','套',['月白', '缃色', '竹青'],['S', 'M', 'L', 'XL'],'交领'),
      ('「棉麻」明制方领短衫(基础)','C010101',380,'女','件',['素', '月白'],['S', 'M', 'L', 'XL'],'方领'),
      ('「真丝双绉」披帛 长款','C040303',680,'女','条',['妃色', '月白', '藕荷'],['均码'],None),
      ('挑花绦带 手工宫绦','C040202',280,'通用','条',['绛', '竹青', '黛'],['均码'],None),
      ('抹额 织锦缀珠款','C040102',380,'女','条',['胭脂', '玄色', '缃色'],['均码'],None),
      ('团扇 绢面手绘','C040203',460,'女','把',['月白', '妃色'],['均码'],None),
      ('荷包 挑花款(两只装)','C040203',180,'通用','组',['竹青', '绛'],['均码'],None),
      ('方巾 明制男装','C040102',320,'男','顶',['玄色'],['均码'],None),
      ('幞头 唐制男装','C040102',580,'男','顶',['玄色'],['均码'],None),
      ('玉禁步 明制正装','C040202',1880,'女','组',['玉白'],['均码'],None),
      ('障扇 长柄绢面','C040203',880,'女','把',['妃色', '月白'],['均码'],None),
      ('香囊 泥金款(两只装)','C040203',260,'通用','组',['绛', '玄色'],['均码'],None),
    ]
    # 定制品:名称 / 三级类目 / 起价 / 性别 / 形制 / 可选面料 / 可选工艺 / 工期 / 模版
    CUS = [
      ("「霁月·流岚」云锦重工交领襦裙","C010203",18000,"女","唐制齐胸襦裙",["云锦","真丝素罗"],["苏绣"],"45–60 天","LT01 唐装模版"),
      ("「妆花霓裳」唐制大袖衫",      "C010301", 9600,"女","大袖衫",   ["云锦"],            ["妆花","苏绣"],"60–90 天","LT01 唐装模版"),
      ("「缂丝团花」唐制半臂",        "C010104", 6800,"女","半臂",     ["真丝素罗","织金缎"],["缂丝"],      "50–70 天","LT01 唐装模版"),
      ("「素罗披帛」唐制套装",        "C010203", 4200,"女","唐制齐胸襦裙",["真丝素罗"],     ["苏绣","平绣"],"35–50 天","LT01 唐装模版"),
      ("「宋锦对襟」宋制褙子",        "C010103", 4680,"女","宋制褙子", ["宋锦","绫"],       ["苏绣","提花"],"30–45 天","LT03 长衫模版"),
      ("「织金妆花」宋制褙子(大袖款)","C010301",11200,"女","宋制褙子", ["云锦"],            ["妆花","织金"],"70–100 天","LT03 长衫模版"),
      ("「草木染」宋制百迭裙",        "C010202", 3280,"女","百迭裙",   ["绫","棉麻"],       ["草木染","平绣"],"25–40 天","LT02 裙装模版"),
      ("「苏绣缂丝」明制马面裙",      "C010201", 7200,"女","明制马面裙",["云锦","织金缎"],   ["苏绣","缂丝"],"50–75 天","LT02 裙装模版"),
      ("「缂丝团花」明制立领长衫",    "C010302", 8400,"女","明制立领长衫",["织金缎","云锦"], ["缂丝","苏绣"],"55–80 天","LT03 长衫模版"),
      ("「盘金襕边」明制马面裙",      "C010201", 6600,"女","明制马面裙",["云锦","织金缎"],   ["盘金绣","织金"],"45–65 天","LT02 裙装模版"),
      ("「莨绸清夏」香云纱明制袄裙",  "C010102", 5200,"女","明制袄裙", ["香云纱"],          ["苏绣","平绣"],"35–50 天","LT02 裙装模版"),
      ("「蜀锦团花」明制圆领袍",      "C020101", 7800,"男","圆领袍",   ["宋锦","云锦"],     ["蜀绣","织金"],"55–75 天","LT03 长衫模版"),
      ("「湘绣补子」男装圆领袍",      "C020101", 9200,"男","圆领袍",   ["云锦"],            ["湘绣","补子"],"60–85 天","LT03 长衫模版"),
      ("「凤仪锦瑟」粤绣重工明制立领长衫(婚服)","C010302",18800,"女","明制立领长衫",["云锦","织金缎"], ["粤绣","盘金绣","织金"],"90–150 天","LT03 长衫模版"),
      ("「双面苏绣」定制云肩",        "C040301", 4800,"女","明制立领长衫",["云锦","织金缎"], ["苏绣","盘金绣"],"20–35 天","LT03 长衫模版"),
      ("「蓝夹缬」童款襦裙",          "C030101", 1680,"童","唐制齐胸襦裙",["棉麻"],         ["蓝夹缬"],    "20–30 天","LT01 唐装模版"),
      ("「妆花莨绸」夏季马面裙",      "C010201", 6200,"女","明制马面裙",["香云纱"],         ["妆花"],      "45–60 天","LT02 裙装模版"),
      ("「盘金重工」唐制大袖衫",      "C010301", 8800,"女","大袖衫",   ["真丝素罗","云锦"], ["盘金绣"],    "50–70 天","LT01 唐装模版"),
      ("「蜀锦联珠」唐制半臂",        "C010104", 5400,"女","半臂",     ["蜀锦","绫"],       ["蜀绣","提花"],"35–50 天","LT01 唐装模版"),
      ("「扎染晕色」唐制襦裙",        "C010203", 3600,"女","唐制齐胸襦裙",["绫","棉麻"],    ["扎染","平绣"],"25–40 天","LT01 唐装模版"),
      ("「素纱单衣」唐制大袖衫(外罩)","C010301", 4400,"女","大袖衫",   ["纱","绡"],         ["平绣"],      "30–45 天","LT01 唐装模版"),
      ("「宋锦暗纹」宋制上襦",        "C010101", 3280,"女","宋制褙子", ["宋锦","绫"],       ["提花","平绣"],"25–40 天","LT03 长衫模版"),
      ("「打籽折枝」宋制褙子",        "C010103", 5200,"女","宋制褙子", ["绫","宋锦"],       ["打籽绣","苏绣"],"40–55 天","LT03 长衫模版"),
      ("「蓝印花布」宋制百迭裙",      "C010202", 2480,"女","百迭裙",   ["棉麻"],            ["蓝印花布"],  "20–35 天","LT02 裙装模版"),
      ("「莨绸对襟」香云纱宋制褙子",  "C010103", 4600,"女","宋制褙子", ["香云纱"],          ["苏绣"],      "30–45 天","LT03 长衫模版"),
      ("「珠绣满工」明制马面裙",      "C010201", 9800,"女","明制马面裙",["云锦","织金缎"],   ["珠绣 / 钉珠","苏绣"],"60–85 天","LT02 裙装模版"),
      ("「双襕织金」明制马面裙",      "C010201", 7600,"女","明制马面裙",["织金缎","云锦"],   ["织金","苏绣"],"50–70 天","LT02 裙装模版"),
      ("「蜀绣缠枝」明制立领长袄",    "C010302", 6800,"女","明制立领长衫",["宋锦","云锦"],   ["蜀绣"],      "45–60 天","LT03 长衫模版"),
      ("「素面高定」明制袄裙(仅上袄)","C010102", 5600,"女","明制袄裙", ["绫","宋锦"],       ["手工锁边","滚边 / 镶边"],"35–50 天","LT02 裙装模版"),
      ("「补子重工」男装圆领袍",      "C020101",10800,"男","圆领袍",   ["云锦","织金缎"],   ["补子","盘金绣"],"70–95 天","LT03 长衫模版"),
      ("「蜡染冰纹」男装道袍",        "C020102", 4200,"男","圆领袍",   ["棉麻"],            ["蜡染"],      "25–40 天","LT03 长衫模版"),
      # **亲子装拆成两个 SPU** —— 一个商品只能挂一个版型,而亲子要两个:
      # 大人是 XZ01 唐制齐胸襦裙(PT01,用料 4.2 米),小孩是 XZ39 童款襦裙
      # (PT79,用料 2.2 米)。原来合成一个商品,于是:
      #   · 版型挂不上(挂大人的,孩子就按成人版裁;挂童款的,大人没版型)
      #   · 那张已有订单**只有一行、一个着装人**(9 岁的王清和)——
      #     **大人那一件根本不在单上**
      # 「着装人」模型本来就是按人一行的,装得下两个人 ——
      # 但 `ordr_item` 没有版型列,**版型只能从商品来,而商品只有一格**。
      # 所以人的那一半够用,版型的那一半不够。
      #
      # ⚠️ **原位改成大人款,童款追加到列表末尾** ——
      # SPU 是按列表下标算的(`lxys_{100000000+i*7919}`),
      # 从中间插一条会把后面每个商品的 SPU 全部挪位。
      # 定价按**用料比**分(4.2 : 2.2 ≈ 66 : 34),合计仍是 ¥5800,不是拍脑袋。
      ("「同心」亲子唐制齐胸襦裙(大人款)","C010203", 3800,"女","唐制齐胸襦裙",["绫","醋酸 / 雪纺等化纤"],["平绣"],"30–45 天","LT01 唐装模版"),
      ("「双面绣」定制团扇(可题字)", "C040202", 1980,"通用","明制立领长衫",["真丝素罗","绫"],["苏绣"],    "15–25 天","LT03 长衫模版"),
      ("「缂丝小件」收藏级香囊",      "C040203", 3600,"通用","明制立领长衫",["织金缎","真丝素罗"],["缂丝"],"20–35 天","LT03 长衫模版"),
      ("「题字腰封」苏绣定制",        "C040201", 2200,"通用","明制立领长衫",["宋锦","绫"],   ["苏绣","滚边 / 镶边"],"15–25 天","LT03 长衫模版"),
      ('「杭罗挑花」唐制交领襦裙','C010203',2980,'女','唐制交领襦裙',['杭罗', '真丝双绉', '绫'],['挑花', '平绣'],'25–40 天','LT01 唐装模版'),
      ('「泥金缠枝」唐制齐腰襦裙','C010203',4200,'女','唐制齐腰襦裙',['素缎', '绫'],['泥金 / 描金', '平绣'],'30–45 天','LT01 唐装模版'),
      ('「手绘敦煌」唐制大袖衫','C010301',6800,'女','大袖衫',['真丝素罗', '绡'],['手绘'],'40–60 天','LT01 唐装模版'),
      ('「暗纹提花」唐制圆领缺胯袍','C020101',5200,'男','唐制圆领缺胯袍',['提花暗纹缎', '素缎'],['织金', '缉线装饰'],'35–50 天','LT03 长衫模版'),
      ('「乔其叠纱」宋制抹胸','C010101',2600,'女','宋制抹胸',['真丝乔其纱', '杭罗'],['平绣'],'20–30 天','LT04 上衣用量体'),
      ('「抽纱雕花」宋制旋裙','C010202',4600,'女','宋制旋裙',['素缎', '真丝双绉'],['抽纱 / 雕绣'],'35–50 天','LT02 裙装模版'),
      ('「锁绣缠枝」宋制长褙子','C010103',5400,'女','宋制长褙子',['宋锦', '素缎', '绫'],['网绣 / 锁绣', '苏绣'],'35–55 天','LT04 上衣用量体'),
      ('「素雅」宋制圆领襕衫','C020101',4400,'男','宋制圆领襕衫',['双宫绸', '素缎'],['缉线装饰'],'30–45 天','LT03 长衫模版'),
      ('「漳绒暗花」明制比甲','C010104',7800,'女','明制比甲',['漳缎', '织金缎'],['盘金绣', '缀珠流苏'],'45–65 天','LT04 上衣用量体'),
      ('「水田衣」明制拼布比甲','C010104',5600,'女','明制比甲',['宋锦', '蜀锦', '素缎'],['拼布 / 水田衣'],'40–60 天','LT04 上衣用量体'),
      ('「织金马面褶」明制曳撒','C020102',9800,'男','明制曳撒',['织金缎', '云锦'],['织金', '盘金绣'],'60–85 天','LT03 长衫模版'),
      ('「素道」明制道袍 定制','C020102',4800,'男','明制道袍',['双宫绸', '素缎', '提花暗纹缎'],['缉线装饰', '绦带盘编'],'30–45 天','LT03 长衫模版'),
      ('「玄素」明制直裰 定制','C020102',4200,'男','明制直裰',['苎麻', '双宫绸'],['缉线装饰'],'25–40 天','LT03 长衫模版'),
      ('「型糊染」明制方领对襟短衫','C010101',1980,'女','明制方领对襟短衫',['棉麻', '苎麻', '竹节棉'],['型糊染', '挑花'],'20–35 天','LT04 上衣用量体'),
      ('「压褶」明制褶裙 定制','C010201',2680,'女','明制褶裙',['真丝双绉', '素缎', '绫'],['压褶定型', '平绣'],'20–35 天','LT02 裙装模版'),
      ('「缀珠流苏」明制披风','C010302',8600,'女','明制披风',['漳缎', '云锦'],['缀珠流苏', '盘金绣'],'50–70 天','LT03 长衫模版'),
      ('「杭罗夏褙」宋制褙子 短款','C010103',2280,'女','宋制褙子',['杭罗', '真丝乔其纱'],['抽纱 / 雕绣'],'20–35 天','LT04 上衣用量体'),
      ('「双面绣」明制立领长衫 男款','C010302',9600,'男','明制立领长衫',['提花暗纹缎', '织金缎'],['苏绣', '盘金绣'],'55–80 天','LT03 长衫模版'),
      ('「素罗大袖」大袖衫·加长','C010301',5800,'女','大袖衫',['真丝素罗', '杭罗'],['手绘', '平绣'],'35–55 天','LT01 唐装模版'),
      ('「坦领」唐制半臂 定制','C010104',3200,'女','半臂',['蜀锦', '素缎'],['蜀绣', '网绣 / 锁绣'],'25–40 天','LT04 上衣用量体'),
      ('「百迭长版」宋制裙','C010202',3400,'女','百迭裙',['真丝双绉', '绫'],['压褶定型', '平绣'],'25–40 天','LT02 裙装模版'),
      ('「女式圆领」唐制袍','C010302',5600,'女','圆领袍',['素缎', '提花暗纹缎'],['织金', '苏绣'],'40–60 天','LT03 长衫模版'),
      ('「长袄」明制袄裙 定制','C010302',6200,'女','明制袄裙',['漳缎', '宋锦'],['盘金绣', '缀珠流苏'],'45–65 天','LT03 长衫模版'),
      ('「苎麻本色」明制方领衫','C010101',1280,'女','明制方领对襟短衫',['苎麻', '天丝麻'],['草木染', '挑花'],'18–30 天','LT04 上衣用量体'),
      ('「棉绸」宋制抹胸 基础款','C010101',880,'女','宋制抹胸',['棉绸(人棉)', '真丝双绉'],['平绣'],'12–20 天','LT04 上衣用量体'),
      ('「描金襕边」明制马面裙','C010201',5800,'女','明制马面裙',['素缎', '提花暗纹缎'],['泥金 / 描金', '平绣'],'35–50 天','LT02 裙装模版'),
      ('「绦带」唐制交领襦裙 长衫版','C010203',3800,'女','唐制交领襦裙',['杭罗', '绫', '素缎'],['绦带盘编', '网绣 / 锁绣'],'28–45 天','LT01 唐装模版'),
      ('「加褶」明制褶裙 重工','C010201',4200,'女','明制褶裙',['宋锦', '蜀锦'],['压褶定型', '盘金绣'],'35–55 天','LT02 裙装模版'),
      ('「竹节」童款交领襦裙 定制','C030101',1280,'童','唐制交领襦裙',['竹节棉', '棉麻'],['型糊染', '挑花'],'18–28 天','LT01 唐装模版'),
      ('「男童」明制道袍 定制','C030102',1680,'童','明制道袍',['苎麻', '竹节棉'],['缉线装饰'],'18–28 天','LT03 长衫模版'),
      # 亲子装的另一半(见上面「大人款」那条的说明)。**追加在末尾,不插中间。**
      ('「同心」亲子童款襦裙(童款)','C030101',2000,'童','童款襦裙',['绫', '醋酸 / 雪纺等化纤'],['平绣'],'30–45 天','LT01 唐装模版'),
    ]
    COLLARS = ["交领","立领","圆领","对襟","直领"]
    REMARKS = ["风格定位:典雅日常款,适合春夏通勤、拍照、节日穿搭",
               "设计灵感:以山间晨雾与清霜为主题,整体低饱和、轻盈雅致",
               "面料说明:实物色以打样色卡为准,批次间存在轻微色差",
               "服务说明:支持到店量体与远程视频量体,远程量体公差另行约定"]

    def _img(spu, n):        # 图片按 SPU 生成,服务端出图,不占仓库体积
        return f"/img/{spu}-{n}.svg"

    _i = 0
    for nm, cat, price, gender, unit, cols, sizes, collar in STD:
        _i += 1
        spu = f"lxys_{100000000+_i*7919:09d}"[:14]
        st = "下架" if _i in (11, 23) else "上架"
        tagp = round(price * 1.12, 2)                       # 吊牌价 = 售价 × 1.12
        c.execute("INSERT INTO product(spu,name,category,kind,status,base_price,template,created,updated,cover,tag_price,unit,gender,points,commission_type,commission_val,on_shelf_at,remark,img_main,img_detail,img_intro)"
                  " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (spu, nm, cat, "标品", st, float(price), None,
                   ago(200-_i*4), ago(_i%30), nm[:2],
                   tagp, unit, gender, int(price*100), 
                   "按比例" if _i%3 else "按固定金额", (10.0 if _i%3 else round(price*0.05,2)),
                   ago(190-_i*4) if st=="上架" else None, REMARKS[_i%4],
                   _img(spu,"main"), json.dumps([_img(spu,f"d{k}") for k in range(1,4)]),
                   json.dumps([_img(spu,"intro")])))
        k = 0
        for col in cols:
            for sz in sizes:
                k += 1
                stock = 0 if (_i%7==3 and k==1) else random.randint(0,80)
                c.execute("INSERT INTO sku VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (f"{spu}-{k:02d}", spu, f"{col}/{sz}", col, sz, float(price),
                           stock, random.randint(0,min(4,stock)) if stock else 0,
                           "停用" if _i==11 else "启用",
                           collar, (str(155+5*(k%4)) if sz in ("S","M","L","XL") else None),
                           f"GG{_i:03d}{k:02d}", round(random.uniform(0.2,1.8),2),
                           round(random.uniform(0.002,0.02),4), int(price*100), _img(spu,f"sku{k}")))
    from fix_product_pattern import 多件词 as _多件词
    for nm, cat, price, gender, xz, mts, kfs, lead, tpl in CUS:
        _i += 1
        spu = f"lxys_{100000000+_i*7919:09d}"[:14]
        mts2 = _legal(mts, kfs)
        st = "上架" if mts2 else "下架"
        tagp = round(price * 1.12, 2)
        c.execute("INSERT INTO product(spu,name,category,kind,status,base_price,template,created,updated,cover,tag_price,unit,gender,points,commission_type,commission_val,on_shelf_at,remark,img_main,img_detail,img_intro)"
                  " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (spu, nm, cat, "定制品", st, float(price), tpl,
                   ago(200-_i*3), ago(_i%30), nm[:2],
                   # **`unit` 从名字派生,不写死「件」。**
                   # 原来这里一律写「件」,于是「亲子唐制襦裙」「唐制套装」
                   # 名字明说是多件,`unit` 却说一件 ——
                   # **一个版型看起来刚好够,没人觉得缺**。
                   # `product_pattern_check` 的 ⑥·1 现在会红。
                   tagp, ("套" if any(w in nm for w in _多件词) else "件"),
                   gender, int(price*100), "按比例", 20.0,
                   ago(190-_i*3) if st=="上架" else None, REMARKS[_i%4],
                   _img(spu,"main"), json.dumps([_img(spu,f"d{k}") for k in range(1,4)]),
                   json.dumps([_img(spu,"intro")])))
        c.execute("INSERT INTO product_custom VALUES(?,?,?,?,?,?)",
                  (spu, xz, ",".join(mts2), ",".join(kfs), lead,
                   None if len(mts2)==len(mts) else
                   "已剔除与所选工艺不相容的面料:" + "、".join(
                       f"{m}(工艺{k}·{_combo_rule.get((_code.get(k),_code.get(m)),'?')})"
                       for m in sorted(set(mts)-set(mts2))
                       for k in kfs
                       if _combo.get((_code.get(k),_code.get(m)))=="不可")))
        c.execute("INSERT INTO sku VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (f"{spu}-01", spu, "定制/定制", "定制", "定制", float(price), 0, 0, "启用",
                   None, None, f"GG{_i:03d}01", None, None, int(price*100), _img(spu,"sku1")))

    # ── 商品(生成部分):由版型 × 相容矩阵长出来 ─────────────────────────
    # 手写的清单覆盖不了 82 个版型 —— 库扩容了商品跟不上,页面上就会出现
    # 「知识库里有这个形制,商品库里一件都没有」的空档。
    #
    # 生成规则:
    #   面料 —— 从 craft_combo 里挑该工艺判「可」的,**生成出来的商品天然不含不可组合**
    #   售价 —— 由 BOM 算出物料成本再乘系数,**每个价格都追得到它的用料**
    # 这是四大库真正接上的地方:版型定用量,矩阵定能不能,BOM 定多少钱。
    import derive_pattern as _dpg
    _CAT_BY_KW = [("马面","C010201"),("褶裙","C010201"),("旋裙","C010202"),("百迭","C010202"),
                  ("三裥","C010202"),("诃子","C010203"),("襦裙","C010203"),("齐胸","C010203"),
                  ("大袖","C010301"),("杂裾","C010301"),("披风","C010302"),("长衫","C010302"),
                  ("长袄","C010302"),("大衫","C010302"),("袄","C010102"),("褙子","C010103"),
                  ("半臂","C010104"),("比甲","C010104"),("罩甲","C010104"),
                  ("道袍","C020102"),("直裰","C020102"),("曳撒","C020102"),("贴里","C020102"),
                  ("圆领","C020101"),("襕衫","C020101"),("缺胯","C020101"),
                  ("连衣裙","C010101"),("短衫","C010101"),("抹胸","C010101"),("衫","C010101")]
    def _cat_of(nm, gender):
        if gender == "童": return "C030102" if "袍" in nm else "C030101"
        for kw, cd in _CAT_BY_KW:
            if kw in nm: return cd
        return "C010101"
    _YA = ["云起","霜序","素心","流岚","栖迟","知秋","青隐","春信","月白","照水",
           "山鸣","露华","梧影","听雪","寒英","澄江","南薰","采薇","陌上","星野"]
    _kf_names = [r[0] for r in c.execute("SELECT name FROM craft WHERE cat='工艺'")]
    _mt_names = [r[0] for r in c.execute("SELECT name FROM craft WHERE cat='材质'")]
    _xz_name  = {r[0]: r[1] for r in c.execute("SELECT code,name FROM craft WHERE cat='形制'")}
    _have_xz  = {r[0] for r in c.execute("SELECT DISTINCT xz FROM product_custom p"
                                         " JOIN craft cr ON cr.name=p.xz")}
    _mprice = {r[0]: r[1] for r in c.execute("SELECT code,price FROM material WHERE cat='主料'")}
    def _tier(nm, g):
        """形制定位 → 允许的面料价格区间(元/米)。"""
        if g == "童" or "改良" in nm or "通勤" in nm:
            return 0, 120          # 童装与改良款:要耐洗、要便宜,配云锦是笑话
        if any(w in nm for w in ("大衫","杂裾","曳撒","贴里","襕","缺胯","圆领袍","竖领")):
            return 150, 99999      # 礼装与男装正装:撑得起高价面料
        return 30, 700             # 其余走中档

    _gi = 0
    for pt in c.execute("SELECT code,name,xz,gender,sizes FROM pattern ORDER BY code").fetchall():
        ptc, ptn, ptxz, ptg, ptsz = pt
        sizes = ptsz.split(",")
        for round_ in range(2):          # 每个版型出一个标品、一个定制品
            _gi += 1
            kf = _kf_names[(_gi * 7 + round_ * 3) % len(_kf_names)]
            # **面料档位要和形制定位匹配。** 只按相容矩阵筛会筛出「改良通勤马面裙用云锦」
            # 这种一眼假的商品(实测生成过一条 ¥32150 的通勤裙)——
            # 相容矩阵管的是「能不能做」,管不了「该不该这么配」。这是两条不同的约束。
            lo, hi = _tier(ptn, ptg)
            ok_mt = [m for m in _mt_names
                     if _combo.get((_code.get(kf), _code.get(m))) == "可"
                     and lo <= _mprice.get(_code.get(m), 0) <= hi]
            if len(ok_mt) < 2: continue
            mts = [ok_mt[(_gi * 5 + i * 11) % len(ok_mt)] for i in range(3)]
            mts = list(dict.fromkeys(mts))
            est = _dpg.estimate(ptc, sizes[min(1, len(sizes)-1)], _code[mts[0]],
                                [_code[kf]], craft_names={r[0]: r[1] for r in
                                c.execute("SELECT code,name FROM craft")})
            cost = est.get("物料成本") or 300
            coef = 2.6 if round_ == 0 else 3.2     # 定制品要摊版房与打样
            price = max(180, int(round(cost * coef, -1)))
            nm = f"「{_YA[_gi % len(_YA)]}」{mts[0]}{ptn}"
            cat = _cat_of(ptn, ptg)
            _i += 1
            spu = f"lxys_{100000000+_i*7919:09d}"[:14]
            kind = "标品" if round_ == 0 else "定制品"
            tagp = round(price * 1.12, 2)
            c.execute("INSERT INTO product(spu,name,category,kind,status,base_price,template,created,updated,cover,tag_price,unit,gender,points,commission_type,commission_val,on_shelf_at,remark,img_main,img_detail,img_intro)"
                  " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (spu, nm, cat, kind, "上架", float(price),
                       ("LT02 裙装模版" if kind == "定制品" else None),
                       ago(180-_i%150), ago(_i%30), nm[1:3],
                       tagp, "件", ptg, int(price*100), "按比例", 20.0,
                       ago(170-_i%150), REMARKS[_i%4],
                       _img(spu,"main"), json.dumps([_img(spu,f"d{k}") for k in range(1,4)]),
                       json.dumps([_img(spu,"intro")])))
            if kind == "定制品":
                c.execute("INSERT INTO product_custom VALUES(?,?,?,?,?,?)",
                          (spu, _xz_name.get(ptxz, ptn), ",".join(mts), kf,
                           est.get("备料天") and f"{est['备料天']}–{est['备料天']+20} 天" or "30–45 天",
                           f"由版型 {ptc} 生成;物料成本 ¥{cost} × {coef} 定价,"
                           f"备料卡在{est.get('最长备料项')}"))
                c.execute("INSERT INTO sku VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (f"{spu}-01", spu, "定制/定制", "定制", "定制", float(price), 0, 0,
                           "启用", None, None, f"GG{_i:03d}01", None, None,
                           int(price*100), _img(spu,"sku1")))
            else:
                for k, sz in enumerate(sizes[:4], 1):
                    stock = random.randint(0, 60)
                    c.execute("INSERT INTO sku VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (f"{spu}-{k:02d}", spu, f"{mts[0]}/{sz}", mts[0], sz,
                               float(price), stock, random.randint(0, min(3, stock)) if stock else 0,
                               "启用", None, None, f"GG{_i:03d}{k:02d}",
                               round(random.uniform(0.2,1.8),2), round(random.uniform(0.002,0.02),4),
                               int(price*100), _img(spu,f"sku{k}")))

    # ── 订单(设计稿「订单管理-订单列表」「交易查询-买家付款」)────────────────
    # 放在商品之后 —— 订单行要引用真实 SPU。原来放在商品之前,只能硬编码一批
    # 早已不存在的 SPU,结果 ordr_item 里 5 个 SPU 全是断链,而且不报错。
    #
    # ⚠️ 订单状态有一条**跨文档冲突**(答案集里的差集 D):
    #    PRD / 状态机 fe-order:待付款 / 方案确认中 / 待发货 / 待收货 / 已完成 / 已关闭(6 个)
    #    设计稿订单列表页签:待付款/待审核/待生产/生产中/已生产/待发货/已发货/待完成/完成/取消(10 个)
    # 不偷偷选一边:`status` 存设计稿口径(页面用),`prd_status` 存 PRD 口径(状态机用),
    # 映射写成显式的一张表。改状态机会让 19 条已推导的订单异常题作废,只用 PRD 口径又对不上页面。
    # 这几个常量原来在订单块头部,搬块时落在了原地(SRC/ACT/DLV 全丢了)——
    # 一起带过来。设计稿:订单来源、绑定活动、配送方式。
    SRC = ["微信小程序","门店 Pad","官网","客服代下单"]
    # **订单存活动编号,不存名字。** 名字会改,编号不会 ——
    # 名字一改,所有历史订单的归因当场断掉,而且断得悄无声息:
    # 按名字 join 出来是 0 单,看起来就像「这个活动没带来成交」。
    #
    # 「没有活动」统一写 None,**不用空字符串** —— 两种写法表示同一件事,
    # 查询时漏掉一种就少算一批(实测原来有 11 单是 ''、46 单是 NULL)。
    ACT = [ACTS[0][0], ACTS[1][0], None, ACTS[2][0]]
    DLV = ["配送到店","配送到客户"]
    ST2PRD = {"待付款":"待付款","待审核":"方案确认中","待生产":"方案确认中","生产中":"方案确认中",
              "已生产":"待发货","待发货":"待发货","已发货":"待收货","待完成":"待收货",
              "完成":"已完成","取消":"已关闭"}
    ST_CUS = ["待付款","待审核","待生产","生产中","已生产","待发货","已发货","待完成","完成","取消"]
    ST_STD = ["待付款","待发货","已发货","待完成","完成","取消"]
    REFUND = ["未退款","未退款","未退款","未退款","退款中","已退款"]
    ADDR = ["上海市静安区南京西路 1266 号 3201 室","浙江省杭州市西湖区文三路 258 号 5 幢 802",
            "江苏省苏州市姑苏区平江路 88 号","上海市徐汇区衡山路 922 弄 12 号 501",
            "广东省广州市越秀区中山五路 33 号 1808","北京市朝阳区建国路 87 号 2604"]
    ORD_REM = [None,None,"客户要求周六送达,已与门店确认",
               "婚期临近,已标记优先排产","客户已确认款样,勿再改配置"]
    # seed.py 的连接没设 row_factory,取出来是元组 —— 显式构造 dict
    _prods = [dict(spu=r[0], name=r[1], kind=r[2], base_price=r[3], category=r[4])
              for r in c.execute(
              "SELECT spu,name,kind,base_price,category FROM product WHERE status='上架'")]
    _std = [p for p in _prods if p["kind"] == "标品"]
    _cus = [p for p in _prods if p["kind"] == "定制品"]
    _custs = [r[0] for r in c.execute("SELECT id FROM customer ORDER BY id")]

    for i in range(46):
        oid = f"64880127{19714560000+i}"
        is_cus = bool(i % 3)
        kind = "定制品订单" if is_cus else "标品订单"
        st = (ST_CUS if is_cus else ST_STD)[i % (10 if is_cus else 6)]
        pool = _cus if is_cus else _std
        n = 1 if i % 4 else 3
        items = [pool[(i * 3 + k) % len(pool)] for k in range(n)]
        goods = round(sum(p["base_price"] for p in items), 2)
        # 定制部件金额:定制品另计,标品为 0(设计稿「基本金额 / 定制部件金额 / 合计总价」)
        custom = round(goods * 0.18, 2) if is_cus else 0.0
        freight = 0.0 if goods >= 2000 else 28.0
        total = round(goods + custom + freight, 2)
        received = total if st in ("已发货","待完成","完成","待生产","生产中","已生产","待发货") else \
                   (0.0 if st in ("待付款","取消") else total)
        day = 10 + (i % 18)
        base_ts = f"2026-08-{day:02d}"
        def _t(off, cond):
            return f"{base_ts} {10+off:02d}:{(i*7)%60:02d}" if cond else None
        seq = ST_CUS if is_cus else ST_STD
        at = seq.index(st) if st in seq else 0
        c.execute("""INSERT INTO ordr(id,customer_id,kind,status,advisor,shop,source,activity,
                     delivery,amount,payable,created,updated,prd_status,goods_amount,freight,
                     received,refund_status,addr,paid_at,audit_at,produced_at,shipped_at,
                     finished_at,cancelled_at,remark)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (oid, _custs[i % len(_custs)], kind, st,
                   _adv_of(_custs[i % len(_custs)]), _shop_of(_custs[i % len(_custs)]),
                   SRC[i % 4], ACT[i % 4], DLV[i % 2], total, total,
                   # created 原来写死 16:16,而 paid_at 是 11:xx —— **35/35 条付款早于下单**。
                   # 一直没被发现,是因为时间顺序检查从 paid_at 才开始查,
                   # **没把 created 放进序列**。改成 09:xx,并把 created 补进那条检查。
                   f"{base_ts} 09:{(i*11)%60:02d}", f"{base_ts} 18:20",
                   ST2PRD[st], goods, freight, received,
                   REFUND[i % 6] if st in ("完成","待完成","已发货") else "未退款",
                   ADDR[i % len(ADDR)],
                   _t(1, at >= 1 or st == "完成"), _t(3, is_cus and at >= 2),
                   _t(5, is_cus and at >= 4), _t(7, at >= (6 if is_cus else 2)),
                   _t(9, st == "完成"), _t(11, st == "取消"),
                   ORD_REM[i % len(ORD_REM)]))
        for p in items:
            base = p["base_price"]
            cust_amt = round(base * 0.18, 2) if is_cus else 0.0
            c.execute("""INSERT INTO ordr_item(order_id,sku,name,tag,price,qty,spu,
                         base_amount,custom_amount,total)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""",
                      (oid, f"{p['spu']}-01", p["name"], p["kind"], base, 1,
                       p["spu"], base, cust_amt, round(base + cust_amt, 2)))

    # ── 量体测量项 ──
    # 08-量体与版型.md 把「胸上围」和「通袖长」列为最高风险的两个尺寸
    # (齐胸类退货主因 / 汉服特有量法,新顾问最常量成西式袖长),
    # 但量体项表里原本一个都没有 —— **知识库说的关键项,系统里采集不到**。
    # 这类「文档和数据对不上」的缺口,建版型库时才暴露出来,补上并写进检查。
    MI=[("MI01","身高","cm",1,1,"必填。要问穿什么鞋,高跟差 5–8cm"),
        ("MI02","体重","kg",1,2,"必填"),
        ("MI03","胸围","cm",1,3,"必填。呼吸状态统一为平静呼气"),
        ("MI13","胸上围","cm",0,4,"**齐胸类必填**。腋下、胸部上方一周,决定裙头位置;不可用胸围推算"),
        ("MI04","腰围","cm",1,5,"必填。要问是否含内搭厚度;马面裙须复核两次"),
        ("MI05","臀围","cm",1,6,"必填"),
        ("MI06","肩宽","cm",0,7,"汉服多连肩袖,容差比西式大"),
        ("MI14","通袖长","cm",0,8,"**指尖到指尖**(双臂平展)。汉服上衣用这一项,不是袖长"),
        ("MI07","袖长","cm",0,9,"西式量法。汉服请改用通袖长 MI14,量错整件报废"),
        ("MI08","衣长","cm",0,10,"后颈点垂直向下;须与客户确认到胯还是到膝"),
        ("MI09","裙长","cm",0,11,"齐胸与齐腰的起量点不同"),
        ("MI10","领围","cm",0,12,"**立领款必填**。±1cm 就影响舒适,须注明是否含内搭"),
        ("MI11","臂围","cm",0,13,"选填"),
        ("MI12","裤长","cm",0,14,"选填")]
    for code,nm,un,rq,so,note in MI:
        c.execute("INSERT INTO measure_item VALUES(?,?,?,?,?,?,?)",
          (code,nm,un,rq,so,"停用" if code=="MI12" else "启用",note))
    # ── 量体模版 ──
    # 编码从 MT 改成 LT:原来量体模版用 MT01,而材质里 MT01 是香云纱 ——
    # **同一个编码指两样东西**。人看得出上下文,按编码查知识库的智能体看不出。
    # 建版型库时要同时引用这两张表,冲突才藏不住了。
    TPL=[("LT01","唐装模版","唐制齐胸襦裙、大袖衫等,采集上身与裙长","启用",
          ["MI01","MI02","MI03","MI13","MI04","MI05","MI06","MI14","MI09"]),
         ("LT02","裙装模版","明制马面裙、宋制百迭裙,重点采集腰臀与裙长","启用",
          ["MI01","MI02","MI04","MI05","MI09"]),
         ("LT03","长衫模版","明制立领长衫、宋制大袖,采集全身","启用",
          ["MI01","MI02","MI03","MI04","MI05","MI06","MI14","MI08","MI10"]),
         ("LT04","上衣用量体","仅上身,用于褙子、比甲等短款","启用",
          ["MI01","MI03","MI06","MI14","MI08"]),
         ("LT05","裤装模版(停用)","已并入裙装模版,保留历史数据","停用",
          ["MI01","MI04","MI12"])]

    # ── 配饰用量体:**知识库写着必须量,而量体项表里一项都没有** ─────

    # `04-配饰.md`:冠/额饰「有头围尺寸,**必须量**,不能按均码发」、

    # 鞋履「**按脚长定制,不按鞋码**」、腕饰「有腕围尺寸」、披帛「长度按身高定」。

    # 而 MI01–MI14 十四项**全是衣服用的**,所以云肩、团扇、香囊、腰封

    # 只能挂「LT03 长衫模版」—— **不是填错了,是没有可填的。**

    #

    # 这是这一轮第三次撞见同一个形状:

    # **规则写在文档里,而库里没有字段承载它,那条规则就永远跑不到。**

    for _c2,_n2,_u2,_srt,_note in [

            ("MI15","头围","cm",15,"**冠/额饰必填**。眉上一指绕头一周;不能按均码发"),

            ("MI16","腕围","cm",16,"腕饰必填。量腕骨最细处"),

            ("MI17","脚长","cm",17,"**鞋履必填,按脚长不按鞋码** —— 汉履楦型与现代鞋不同")]:

        c.execute("INSERT INTO measure_item(code,name,unit,required,sort,status,note)"

                  " VALUES(?,?,?,0,?,'启用',?)", (_c2,_n2,_u2,_srt,_note))

        # ── 量体项补齐:**文档里写着关键尺寸,而系统里没有这一项** ─────────
    # `01-形制.md` 的 XZ03 明制马面裙,关键尺寸里有「**马面宽度**」——
    # 而 MI01–MI17 一项都没有。**这条文档里写着的尺寸,系统永远量不到。**
    # 和头围/腕围/脚长是同一回事,只是这次是被 `xingzhi_check` 抓出来的
    # (那三项是我看 04-配饰.md 发现的 —— **人眼扫文档会漏,检查不会**)。
    c.execute("INSERT INTO measure_item(code,name,unit,required,sort,status,note)"
              " VALUES('MI18','马面宽度','cm',0,18,'启用',"
              "'**马面裙必填**。前后马面的门幅宽度,决定褶裥分配;"
              "马面裙工艺难度极高,这一项错了整条裙子的比例就错了')")
    TPL = TPL + [("LT06", "配饰用量体", "配饰按身高/头围/腕围/脚长定,不按三围", "启用",
                  ["MI01", "MI04", "MI06", "MI10", "MI15", "MI16", "MI17"])]

    # 三处模板漏了形制的关键尺寸(`xingzhi_check` 抓的):
    #   LT01 缺「衣长」MI08 —— 影响 10 个版型(大袖衫、唐制交领襦裙…)
    #   LT04 缺「胸上围」MI13、「腰围」MI04 —— 影响 4 个版型
    #   LT02 缺「马面宽度」MI18 —— 马面裙
    # **漏一项不是「少量一个数」**,是这个形制最敏感的那一项没量。
    # ⚠️ **LT04 不补腰围和胸上围。** 第一版补了,当场打破 `fitting.py` 的
    # 那条夹具(「应该有客户因为量体模版不含腰围/裙长而需补量」)——
    # 而那条夹具拦得对:**把腰围塞进「上衣用量体」,它就不再是上衣用量体了。**
    #
    # 查下来只有两个形制在 LT04 上缺项,而缺的原因是**版型挂错了模板**:
    #   · 改良汉元素连衣裙(要腰围)用「上衣用量体」—— 一条连衣裙用上衣模版量
    #   · 宋制抹胸(要胸上围)用「上衣用量体」—— 胸上围决定裙头位置,上衣模版没有
    # **不是模板缺项,是版型挂错。** 见下面 `_换模板`。
    # LT02 裙装模版补胸围 MI03 和衣长 MI08:
    # **连衣裙是一件衣服**,不是一条裙子 —— 上半身也要量。
    # 补这两项不会打破 fitting 那条夹具(它靠的是「上衣用量体」没有腰围/裙长)。
    # LT02 还要补「裤长」MI12 —— **这是一个没兑现的声明**。
    # LT05 裤装模版的说明写着「**已并入裙装模版**,保留历史数据」,
    # 可裙装模版里根本没有裤长:并的时候把这一项漏了。
    # 于是 2 个在售的宋裤商品(「星野」双宫绸、「云起」电力纺)走 PT10 → LT02,
    # **量体时从来不问裤长**,而 `08-量体与版型.md` 早就写着宋裤的关键尺寸含裤长。
    #
    # 这条一直没被抓到,是因为 `01-形制.md` 里 XZ08 宋裤的「关键尺寸」**是空的** ——
    # 而 `xingzhi_check` 的模板覆盖检查是拿 01 的关键尺寸去比的。
    # **一栏空着,那个形制就整条跳过检查** —— 空值和「没问题」在检查输出上一模一样。
    #
    # 补裤长不是推翻「合并模板」那个决定,是**把那个决定执行完**。
    _补项 = {"LT01": ["MI08"], "LT02": ["MI18", "MI03", "MI08", "MI12"]}
    TPL = [(c1, n1, d1, s1, it + [x for x in _补项.get(c1, []) if x not in it])
           for c1, n1, d1, s1, it in TPL]
    for code,nm,de,st,items in TPL:
        c.execute("INSERT INTO measure_tpl VALUES(?,?,?,?,?,?)",
          (code,nm,de,st,"60000008",f"2026-08-2{TPL.index((code,nm,de,st,items))} 16:16"))
        for j,it in enumerate(items):
            c.execute("INSERT INTO tpl_item VALUES(?,?,?)",(code,it,j+1))
    # ── 客户量体档案(定制品订单的客户)──
    # **加量体项的时候这里要一起加** —— 少一个当场 KeyError,
    # 而且是在造数据的半路崩,留下**看起来正常的残缺库**。
    IDEAL={"MI01":165,"MI02":52,"MI03":86,"MI04":68,"MI05":92,"MI06":38,
           "MI07":56,"MI08":110,"MI09":98,"MI10":34,"MI11":26,"MI12":100,
           "MI13":80,"MI14":180,
           "MI15":56,   # 头围
           "MI16":16,   # 腕围
           "MI17":24,   # 脚长
           "MI18":33}   # 马面宽度
    cust_ids=[r[0] for r in c.execute("SELECT DISTINCT customer_id FROM ordr WHERE kind='定制品订单' LIMIT 18")]
    for k,cid in enumerate(cust_ids):
        tpl=TPL[k%4][0]
        for it in dict(TPL[k%4][4] and {i:1 for i in TPL[k%4][4]}):
            c.execute("INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by,"
                      "measured_at,method,cond_inner,cond_shoe,cond_breath) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)",
              (cid,tpl,it,round(IDEAL[it]+random.uniform(-6,6),1),_adv_any(),
               f"2026-0{6+k%3}-1{k%9} 14:30", "远程" if k%5==3 else "到店",
               ["无","薄","厚"][k%3], ["赤足","平底","高跟"][k%3], "平静呼气"))
    # 体型特征:每 4 个客户里有 1 个记了 —— 记了的必须走全定制,与差值无关
    FEAT=[("溜肩","肩斜大于常规 3°,标准版肩部会起空"),
          ("含胸","前胸量偏小而后背偏宽,需前后片分别调整"),
          ("高低肩","左右肩差 1.5cm 以上,须单独出版"),
          ("腹凸","腰腹差小,标准腰位会顶")]

    # ── 账户:按手机号归,一个人一个 ────────────────────────────────
    # 106 条门店档案只有 90 个不同手机号 —— 那 16 组重号按项目自己的判定标准
    # (姓名 + 生日 + 地址三项全同)就是同一个人,**按手机号建账户天然把它们并了**。
    #
    # 密码:**只存 PBKDF2-HMAC-SHA256 哈希 + 每账户独立的盐,绝不存明文**。
    # demo 里也不例外 —— 一份会被别人照抄的代码,不该示范存明文密码。
    import hashlib, secrets
    PWD_ITER = 120_000
    def _hash(pw, salt):
        return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), PWD_ITER).hex()

    phones = [r[0] for r in c.execute(
        "SELECT phone FROM customer WHERE phone IS NOT NULL GROUP BY phone ORDER BY phone")]
    for i, ph in enumerate(phones):
        aid = f"U{20000+i}"
        # 四成用户自设了账号密码,其余只用手机号 —— 真实产品里就是这个比例感
        if i % 5 < 2:
            login = f"lx_{ph[-6:]}"
            salt = secrets.token_hex(16)
            # demo 口令不是真凭据,但也只以哈希形态落库
            h = _hash(f"demo-{ph[-4:]}-pwd", salt)
            algo = f"pbkdf2_sha256${PWD_ITER}"
        else:
            login = salt = h = algo = None
        cu = c.execute("SELECT name,addr,shop,province,city FROM customer WHERE phone=? "
                       "ORDER BY created LIMIT 1", (ph,)).fetchone()
        pref = ["微信", "电话", "短信"][i % 3]
        c.execute("INSERT INTO account VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (aid, ph, login, algo, salt, h, "正常", ago(200 - i % 150),
                   ago(i % 40) if i % 3 else None,
                   cu[0] if cu else None, pref,
                   # ⚠️ 直接用 addr,**不要再拼省市** —— D1 那次修完之后
                   # addr 本身已经含省市了,再拼一遍就成了
                   # 「河北省衡水市河北省衡水市武邑县961号」。
                   # 两个改动单独看都对,**撞在一起就重复**。
                   cu[1] if cu else None,
                   cu[2] if cu else None,
                   None,                       # self_wearer_id 建完着装人再回填
                   # 协议版本:**大多数在当前版,少数落后** ——
                   # 全都落后的话「需重新取得同意」这盏灯就一直亮,
                   # **全都亮的灯等于没有灯**,顾问三天就学会无视它。
                   ("v2.1" if i % 7 == 2 else "v2.3"),
                   ("v1.4" if i % 11 == 3 else "v1.5"),
                   1 if i % 3 else 0,
                   None, None, 0, None))
        c.execute("UPDATE customer SET account_id=? WHERE phone=?", (aid, ph))
        # A6:每 7 个账户里有 1 个换过号,旧号留成别名 ——
        # 合并流程写着「手机号取新号」,不留别名就等于让客户失联:
        # **客户拿旧号来问,系统会说查无此人。**
        if i % 7 == 3:
            c.execute("INSERT OR IGNORE INTO phone_alias VALUES(?,?,?,?)",
                      (f"1{(int(ph)+7_0000_0000) % 10_000_000_000:010d}", aid,
                       "换号,旧号保留", ago(120 + i % 60)))

    # ── 着装人:把「账号」和「衣服穿在谁身上」拆开 ────────────────────
    # 老的量体记录一律归到该账号的「本人」着装人 —— 历史数据口径不变。
    KID_M = ["砚舟", "子墨", "望舒", "知许", "星野"]
    KID_F = ["星芜", "昭昭", "令仪", "清和", "若薇"]
    def _w(i, cid, name, gender, bday, rel, pa=None, pb=None, h=None, phone=None):
        wid = f"W{cid[1:]}-{i}"
        # **身份绑账户,不绑门店档案** —— 档案可能有好几条,账户只有一个
        aid = c.execute("SELECT account_id FROM customer WHERE id=?", (cid,)).fetchone()[0]
        c.execute("INSERT INTO wearer VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (wid, cid, aid, name, gender, bday, rel, phone, pa, pb, h, "在用", T.isoformat()))
        return wid
    def _consent(n, wid, scope, by, rel, at):
        c.execute("INSERT INTO consent VALUES(?,?,?,?,?,?,?,?)",
                  (f"CS{2000+n}", wid, scope, by, rel, "门店纸质", at, None))

    # ── 账户生命周期:锁定 / 注销中 / 已注销 ────────────────────────────
    # **「注销」和「数据删除」是两件事**,个保法里也是分开的:
    #   注销中 —— 冷静期,数据还在,可以撤回
    #   已注销 —— 个人数据必须**真的删掉**
    #
    # 已注销账户因此**不该有着装人**(数据已删),所以 A3 要加这条例外。
    # 手机号是 NOT NULL UNIQUE,删不掉 —— 真实系统的做法是换成**墓碑值**:
    # 唯一性还在,真号已经没了,拿旧号也查不到人。
    # 注销 / 锁定的目标要挑**没有在办业务**的账户 —— 这是真实业务规则:
    # 有在办维修工单、未完成订单、活跃量体记录的账户,不该被注销,
    # **冷静期存在的意义正是等这些事了结**。
    # 顺带的好处:评测夹具不会被一次注销级联打断。
    _busy = {r[0] for r in c.execute("""
        SELECT DISTINCT k.account_id FROM customer k
        WHERE k.account_id IS NOT NULL AND (
             EXISTS(SELECT 1 FROM measure_rec m WHERE m.customer_id=k.id)
          OR EXISTS(SELECT 1 FROM maintain t WHERE t.customer_id=k.id)
          OR EXISTS(SELECT 1 FROM ordr o WHERE o.customer_id=k.id
                    AND o.status NOT IN ('完成','取消')))""")}
    _accs = [r[0] for r in c.execute("SELECT id FROM account ORDER BY id")
             if r[0] not in _busy]
    for _n, _aid in enumerate(_accs):
        if _n % 12 == 1:            # 3 个:锁定(连续输错密码)
            c.execute("UPDATE account SET fail_count=?, locked_until=?, status='锁定' "
                      "WHERE id=?", (5 + _n % 3, ago(-1), _aid))
        elif _n % 12 == 5:         # 3 个:注销中,冷静期 15 天,数据还在
            c.execute("UPDATE account SET status='注销中', closed_at=?, marketing_consent=0 "
                      "WHERE id=?", (ago(_n % 10 + 2), _aid))
        elif _n % 12 == 9:         # 3 个:已注销,个人数据已清除
            c.execute("UPDATE account SET status='已注销', closed_at=?, purge_at=?, "
                      "phone=?, login_name=NULL, pwd_algo=NULL, pwd_salt=NULL, pwd_hash=NULL, "
                      "display_name=NULL, contact_pref=NULL, default_addr=NULL, "
                      "marketing_consent=0, self_wearer_id=NULL WHERE id=?",
                      (ago(60 + _n % 20), ago(45 + _n % 20), f"DELETED-{_aid}", _aid))
            # **注销不是删掉一行,是决定「哪些必须删、哪些必须留」:**
            #   必须删  —— 身体数据(着装人 / 量体 / 体型特征 / 同意):敏感个人信息,没有保留依据
            #   必须留  —— 订单、售后:履行合同与法定义务所需的经营记录
            #   去标识化 —— 门店档案上的姓名、手机、地址、微信、邮箱
            # 删多了违约,删少了违法。上一版只清了账户那一行,
            # 结果 14 条量体记录成了孤儿 —— **人删了,身体数据还躺在库里。**
            _cids = [r[0] for r in c.execute(
                "SELECT id FROM customer WHERE account_id=?", (_aid,))]
            for _cd in _cids:
                c.execute("DELETE FROM measure_rec WHERE customer_id=?", (_cd,))
                c.execute("""DELETE FROM body_feature WHERE wearer_id IN
                             (SELECT id FROM wearer WHERE customer_id=?)""", (_cd,))
                c.execute("""DELETE FROM consent WHERE wearer_id IN
                             (SELECT id FROM wearer WHERE customer_id=?)""", (_cd,))
                c.execute("DELETE FROM wearer WHERE customer_id=?", (_cd,))
                c.execute("""UPDATE customer SET name='已注销用户', phone=?, phone_tail=NULL,
                             addr=NULL, email=NULL, wechat=NULL, birthday=NULL, remark=NULL
                             WHERE id=?""", (f"DELETED-{_cd}", _cd))

    # ── 注销的下游还有一处:**挂在队列里的工单** ─────────────────────
    # 上面清了量体、着装人、同意,把门店档案去标识化了,但漏了 task ——
    # 于是一条「客户合并确认」还挂在待处理队列里,而两条档案里已经
    # 一个字都比不了了(姓名成了「已注销用户」,生日地址全空)。
    #
    # 更要命的是**真值**:真值在建这对档案时就标好了「同名不同人」,
    # 而那时候还没脱敏。**真值必须是最终数据的函数** —— 数据后来变了,
    # 真值没跟着变,评测就会去要一个数据里根本不存在的答案,
    # 而报错会说「规则判不出」,指向的是规则,不是指向真值过期。
    # 这个坑这个项目在 BP-03 上踩过一次,这是第二次。
    _purged = {r[0] for r in c.execute(
        "SELECT id FROM customer WHERE name='已注销用户'").fetchall()}
    _drop = set()
    for _t in c.execute("SELECT id,ref_id FROM task WHERE type='客户合并确认'").fetchall():
        if _purged & set((_t[1] or "").split("|")):
            # 队列里关掉:注销后没有可比对的数据,这条合并不该再等人判
            c.execute("UPDATE task SET status='已关闭' WHERE id=?", (_t[0],))
            _drop.add(_t[0][1:])          # 工单 TMERGE-09 → 用例 MERGE-09
    if _drop:
        truths[:] = [t for t in truths if t[0] not in _drop]
        print(f"  [注销] {len(_drop)} 条客户合并工单因档案已注销而关闭,对应真值一并撤下:"
              f"{sorted(_drop)}")

    # ── A3/A7/A8:**每个账户必须有一个「本人」着装人,而且必须成年** ──────
    # 账户 = 一个人;那个人本身就是第一个着装人。原来只给 18 个有量体记录的
    # 客户建了着装人,于是 72 个账户底下空着 —— 空账户在业务上没有意义:
    # **一个连「衣服穿在谁身上」都答不出的账户,做定制没法用。**
    #
    # 本人取该账户下**最早建档**的那条门店档案(一个账户可能有多条)。
    # 联系手机号默认等于账户登录号 —— 本人这一个是重合的,别的着装人各留各的。
    cn = 0
    for a in c.execute("SELECT id, phone, display_name FROM account ORDER BY id").fetchall():
        aid, aph, anm = a
        # 已注销的账户不建着装人 —— **个人数据已删除,建回去就是把删掉的又写回来**
        if c.execute("SELECT status FROM account WHERE id=?", (aid,)).fetchone()[0] == "已注销":
            continue
        cu = c.execute("""SELECT id,name,gender,birthday FROM customer
                          WHERE account_id=? ORDER BY created LIMIT 1""", (aid,)).fetchone()
        if not cu: continue
        cid, nm, gd, bd = cu
        gd = gd if gd in ("男", "女") else "女"
        bd = bd or "1992-01-01"
        # A7:账户持有人必须成年。种子里客户生日都在 26–46 岁,这里再兜一道 ——
        # **规范说了必须成年,就不能指望「数据碰巧是成年的」**。
        if (T - date.fromisoformat(bd)).days / 365.25 < 18:
            bd = (T - timedelta(days=int(30 * 365.25))).isoformat()
        hh = c.execute("SELECT value FROM measure_rec WHERE customer_id=? AND item='MI01'",
                       (cid,)).fetchone()
        self_h = round(hh[0], 1) if hh else (171.2 if gd == "男" else 159.6)
        # 边界用例那些客户的 name 存的是**描述**(「实付 15,000 元(高价值边界)」),
        # 不是人名 —— 直接拿来当着装人姓名会出现「本人:高价值边界」这种记录。
        # 姓名是要打印在工单上给师傅看的,不能是测试说明。
        _nm = nm or anm or "本人"
        if any(x in _nm for x in ("边界", "命中", "元", "+", "同时")) or len(_nm) > 6:
            _nm = f"{_nm[0] if _nm[0].isalpha() or '\u4e00' <= _nm[0] <= '\u9fff' else '客'}女士"
        wid = _w(0, cid, _nm, gd, bd, "本人", h=self_h, phone=aph)
        c.execute("UPDATE account SET self_wearer_id=? WHERE id=?", (wid, aid))
        # 该账户名下所有门店档案的量体记录,都归到本人
        c.execute("""UPDATE measure_rec SET wearer_id=? WHERE wearer_id IS NULL
                     AND customer_id IN (SELECT id FROM customer WHERE account_id=?)""", (wid, aid))
        _consent(cn, wid, "身体数据", nm or anm or "本人", "本人",
                 f"2026-0{6+cn%3}-1{cn%9}"); cn += 1

    for k, cid in enumerate(cust_ids):
        row = c.execute("SELECT name,gender,birthday FROM customer WHERE id=?", (cid,)).fetchone()
        nm, gd, bd = (row or ("客户", "女", "1992-01-01"))
        gd = gd if gd in ("男", "女") else "女"
        bd = bd or "1992-01-01"
        # 本人已在上面按账户建好了 —— **不再建第二个**(A8:有且只有一个「本人」)
        aid0 = c.execute("SELECT account_id FROM customer WHERE id=?", (cid,)).fetchone()[0]
        w_self = c.execute("SELECT self_wearer_id FROM account WHERE id=?", (aid0,)).fetchone()[0]
        if not w_self: continue

        # 每隔一个账号挂一个孩子 —— 孩子才是这个模块真正要管的对象
        if k % 2: continue
        # 配偶(只为了父母身高:靶身高法的唯一个体化输入)
        sg = "男" if gd == "女" else "女"
        # A9:配偶留**自己的**联系号;孩子不留(可空)——
        # 合成一个字段的话,孩子就被迫要有手机号,或者妈妈的号在库里唯一冲突。
        _sp_phone = f"1{(int(c.execute('SELECT phone FROM account WHERE id=?',(
            c.execute('SELECT account_id FROM customer WHERE id=?',(cid,)).fetchone()[0],)
        ).fetchone()[0]) + 31_4159_265) % 10_000_000_000:010d}"
        w_sp = _w(1, cid, f"{nm[0]}{'先生' if sg=='男' else '女士'}", sg,
                  "1990-05-20", "配偶", h=174.0 if sg == "男" else 161.0, phone=_sp_phone)
        _consent(cn, w_sp, "身体数据", nm, "配偶", f"2026-0{6+k%3}-1{k%9}"); cn += 1
        # 孩子:年龄铺开 3–14 岁,覆盖「学龄前 / 学龄 / 突增期」三段
        age = [3, 5, 7, 9, 11, 13, 14, 4, 6][(k // 2) % 9]
        kg = "女" if (k // 2) % 2 else "男"
        kname = nm[0] + ((KID_F if kg == "女" else KID_M)[(k // 2) % 5])
        kbd = (T - timedelta(days=int(age * 365.25) + (k * 11) % 300)).isoformat()
        pa, pb = (w_self, w_sp) if gd == "男" else (w_sp, w_self)
        w_kid = _w(2, cid, kname, kg, kbd, "女" if kg == "女" else "子", pa, pb)
        # 未成年:同意人必须是监护人,且关系要记下来
        _consent(cn, w_kid, "未成年人", nm, "监护人(母)" if gd == "女" else "监护人(父)",
                 f"2026-0{6+k%3}-1{k%9}"); cn += 1
        _consent(cn, w_kid, "身体数据", nm, "监护人(母)" if gd == "女" else "监护人(父)",
                 f"2026-0{6+k%3}-1{k%9}"); cn += 1
        # 孩子的量体记录:**故意铺开新旧** —— 有的还在有效期,有的早就该复量了。
        # 这不是脏数据,这是真实业务:半年前的记录被顺手复用,正是童装返工第一大原因。
        days_ago = [40, 95, 150, 210, 280, 330][(k // 2) % 6]
        mdate = (T - timedelta(days=days_ago)).isoformat()
        base = {2:88.5,3:96.8,4:103.1,5:109.7,6:116.0,7:121.7,8:127.0,9:132.0,
                10:137.0,11:142.5,12:148.8,13:156.0,14:162.5}[age]
        kid_h = round(base + random.uniform(-5, 5), 1)
        for it, v in (("MI01", kid_h), ("MI03", round(kid_h*0.47, 1)),
                      ("MI04", round(kid_h*0.42, 1)), ("MI09", round(kid_h*0.55, 1)),
                      ("MI14", round(kid_h*1.03, 1))):
            c.execute("INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by,"
                      "measured_at,method,wearer_id,cond_inner,cond_shoe,cond_breath) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (cid, TPL[k % 4][0], it, v, _adv_any(),
                       f"{mdate} 15:00", "到店", w_kid,
                       "薄", "平底", "平静呼气"))
    # ── 内容管理 ──
    CK=["品牌故事","穿搭指南","工艺科普","活动预告"]
    CH=["小程序首页","会员中心","门店Pad","公众号"]
    for i in range(16):
        c.execute("INSERT INTO content VALUES(?,?,?,?,?,?,?,?)",
          (f"CT{100+i}",
           ["云锦织造的七十二道工序","唐制齐胸襦裙的日常穿法","缂丝为什么被称为织中之圣",
            "秋季新品预览:妆花缎系列","如何挑选适合自己的马面裙","明制立领长衫的历史沿革",
            "苏绣双面绣工艺解析","汉服形制入门:唐宋明三制对比","盘扣的十二种做法",
            "香云纱的晒莨工艺","品牌十周年回顾","门店预约量体全流程","定制方案确认要点",
            "配饰搭配的三个原则","真丝面料的保养方法","冬季新品预告"][i],
           CK[i%4],"已发布" if i%5 else "草稿",CH[i%4],"60000009",
           f"2026-0{6+i%3}-{10+i%18:02d} 10:00",random.randint(120,8600)))

    # ── 营销活动 ──(花名册在模块级 ACTS,**订单块在这之前就要用它的编号**)
    COSTITEM=["场地租赁","物料印刷","KOL 投放","礼品采购","摄影摄像","门店陈列"]
    for i,(code,nm,kd,st,sd,ed,bg) in enumerate(ACTS):
        su=random.randint(30,480) if st!="未开始" else 0
        od=rows_n=random.randint(5,90) if st!="未开始" else 0
        c.execute("INSERT INTO activity VALUES(?,?,?,?,?,?,?,?,?,?,?)",
          (code,nm,kd,st,sd,ed,ACT_SHOP.get(code,"全渠道") if kd=="门店" else "全渠道",
           bg,su,od,sd+" 09:00"))
        for k in range(3 if st!="未开始" else 1):
            c.execute("INSERT INTO activity_cost(activity,item,amount,note,created_by,created) VALUES(?,?,?,?,?,?)",
              (code,COSTITEM[(i+k)%6],round(bg*random.uniform(.08,.32),2),
               "已开票" if k%2 else "待开票","60000009",f"{sd} 1{k}:20"))
    # 一部分日程绑到活动上。**这段必须放在活动建完之后** ——
    # 上一版写在日程那一段里,那时 activity 表还是空的,SELECT 返回空列表,
    # 循环一次都没跑,结果是 0 条绑定,而且**一句报错都没有**。
    # 空查询不报错,是种子脚本里最常见的静默失败。
    # 一部分日程绑到活动上。**不是全绑** —— 全绑和全不绑一样没信息量:
    # 界面上「绑定活动」这一列要么永远有值要么永远为空,都看不出这列在干嘛。
    _acs = [r[0] for r in c.execute(
        "SELECT code FROM activity WHERE status='进行中'").fetchall()]
    if _acs:
        for _k, _sc in enumerate(c.execute("SELECT id FROM schedule ORDER BY id").fetchall()):
            if _k % 4 == 1:
                c.execute("UPDATE schedule SET activity_code=? WHERE id=?",
                          (_acs[_k % len(_acs)], _sc[0]))

    # ── 邀请码(两个批次)──
    for b,(act,n) in enumerate([("AC2603",40),("AC2605",30)]):
        for k in range(n):
            used = k < n//3
            c.execute("INSERT INTO invite_code VALUES(?,?,?,?,?,?,?)",
              (f"INV{b+1}{k:04d}",f"B{b+1:02d}",act,
               "已使用" if used else ("已作废" if k>=n-3 else "未使用"),
               cust[k%len(cust)][0] if used else None,
               f"2026-08-{10+k%18:02d} 14:00" if used else None,"2026-07-20 10:00"))
    # ── 页面管理 ──
    BK=["普通图片","轮播图片","商品列表","热点图"]
    PAGES=[("PG01","小程序首页","小程序","已发布"),("PG02","会员中心","小程序","已发布"),
           ("PG03","秋季新品专题","小程序","草稿"),("PG04","门店预约引导页","小程序","已发布"),
           ("PG05","非遗联名专题","小程序","草稿"),("PG06","Pad 接待首屏","门店Pad","已发布")]
    for i,(code,nm,ch,st) in enumerate(PAGES):
        c.execute("INSERT INTO page VALUES(?,?,?,?,?,?)",
          (code,nm,ch,st,"60000009",f"2026-08-{18+i%12:02d} 1{i%9}:30"))
        for k in range(2+i%3):
            kd=BK[(i+k)%4]
            c.execute("INSERT INTO page_block(page,sort,kind,title,cfg) VALUES(?,?,?,?,?)",
              (code,k+1,kd,
               {"普通图片":"品牌主视觉","轮播图片":"新品轮播","商品列表":"热销推荐","热点图":"款式导航"}[kd],
               {"普通图片":"1 张 / 750×420","轮播图片":"4 张 / 自动播放 3s",
                "商品列表":"取自品类 C0101 / 最多 8 个","热点图":"1 张 / 5 个热区"}[kd]))
    # ── 系统编码 ──
    SC=[("SC-ORD-01","订单来源","微信小程序","wxapp",1),("SC-ORD-02","订单来源","门店Pad","pad",2),
        ("SC-ORD-03","订单来源","门店A","shopA",3),("SC-ORD-04","订单来源","门店B","shopB",4),
        ("SC-DLV-01","配送方式","配送到店","to_shop",1),("SC-DLV-02","配送方式","配送到客户","to_cust",2),
        ("SC-APT-01","预约方式","到店量体","onsite_m",1),("SC-APT-02","预约方式","到店试衣","onsite_t",2),
        ("SC-APT-03","预约方式","上门沟通","visit",3),("SC-APT-04","预约方式","电话回电","callback",4),
        ("SC-REF-01","退款失败码","渠道响应超时","TIMEOUT",1),
        ("SC-REF-02","退款失败码","退款金额超过原交易","AMOUNT_EXCEED",2),
        ("SC-REF-03","退款失败码","收款账户已注销","ACCOUNT_CLOSED",3),
        ("SC-REF-04","退款失败码","重复请求","DUPLICATE",4),
        ("SC-REF-05","退款失败码","商户账户余额不足","INSUFFICIENT_BALANCE",5),
        ("SC-REF-06","退款失败码","审批状态不允许","NOT_APPROVED",6)]
    for code,cat,nm,vl,so in SC:
        c.execute("INSERT INTO sys_code VALUES(?,?,?,?,?,?,?)",
          (code,cat,nm,vl,so,"启用" if code!="SC-ORD-04" else "停用",
           "与支付渠道返回码一一对应" if cat=="退款失败码" else ""))
    # ── 下载任务 ──
    DT=[("DL2609010001","客户档案","生命周期=流失","已完成",10,4),
        ("DL2609010002","操作日志","全部","已完成",18,6),
        ("DL2608310003","商品库","类型=定制品","已过期",5,2),
        ("DL2608310004","客户档案","归属店铺=SH001","失败",0,0),
        ("DL2609010005","交易查询","状态=待付款","生成中",0,0)]
    for i,(did,kd,fl,st,rn,sz) in enumerate(DT):
        c.execute("INSERT INTO download_task VALUES(?,?,?,?,?,?,?,?,?)",
          (did,kd,fl,st,rn,sz,"60000008",f"2026-0{8+i%2}-3{i%2} 1{i}:0{i}",
           f"2026-09-0{2+i%3} 1{i}:0{i}"))

    # ── 会员等级配置(后台 PRD 6.2:滚动 12 个月实付金额或订单数,任一满足即升级)──
    # 设计稿「会员等级」把规则拆成两条:购物规则(实付/单数)+ 积分规则(所需积分)
    LV=[("L0","普通",0,0,0,"注册后默认等级",0,"下单实付每 1 元累积 1 分"),
        ("L1","银卡",5000,2,1,"滚动 12 个月实付 ≥5000 元 或 完成订单 ≥2 单",3000,"下单实付每 1 元累积 1.2 分"),
        ("L2","金卡",15000,4,2,"滚动 12 个月实付 ≥15000 元 或 完成订单 ≥4 单",10000,"下单实付每 1 元累积 1.5 分"),
        ("L3","黑金",30000,6,3,"滚动 12 个月实付 ≥30000 元 或 完成订单 ≥6 单",25000,"下单实付每 1 元累积 2 分")]
    for code,nm,am,od,so,nt,np_,pr in LV:
        c.execute("INSERT INTO level_cfg VALUES(?,?,?,?,?,?,?,?,?)",
                  (code,nm,am,od,so,"启用",nt,np_,pr))
    # 按规则重算客户等级(每日计算,订单完成 7 个自然日后计入)
    def level_of(amt,od):
        for code,nm,am,ordn,so,_,_np,_pr in reversed(LV):
            if so and (amt>=am or od>=ordn): return nm
        return "普通"
    for r in list(c.execute("SELECT id,amount_12m,orders_12m FROM customer")):
        c.execute("UPDATE customer SET level=? WHERE id=?",(level_of(r[1] or 0,r[2] or 0),r[0]))
    # ── 客户标签 ──
    TAGS=[("TG01","高意向","意向度"),("TG02","观望中","意向度"),("TG03","价格敏感","意向度"),
          ("TG04","唐制偏好","款式偏好"),("TG05","宋制偏好","款式偏好"),("TG06","明制偏好","款式偏好"),
          ("TG07","重复购买","行为"),("TG08","仅线上","行为"),("TG09","到店频繁","行为"),
          ("TG10","已流失(停用)","行为")]
    for i,(code,nm,gp) in enumerate(TAGS):
        c.execute("INSERT INTO tag VALUES(?,?,?,?,?,?)",
          (code,nm,gp,"停用" if code=="TG10" else "启用",random.randint(3,42),
           f"2026-08-{18+i%12:02d} 1{i%9}:20"))
    # ── 审批单(三类高风险操作,PRD 第 8 章)──
    APV=[("AP-LV-001","等级调整","C10008",'{"from":"金卡","to":"黑金"}',"待审批","60000001"),
         ("AP-PT-001","积分调整","C10012",'{"delta":5000,"reason":"活动补发"}',"待审批","60000004"),
         ("AP-TR-001","客户转移","C10003|C10005",'{"to_advisor":"A03 沈砚","n":2}',"待审批","60000001"),
         ("AP-LV-002","等级调整","C10001",'{"from":"银卡","to":"金卡"}',"已通过","60000001"),
         ("AP-PT-002","积分调整","C10020",'{"delta":-2000,"reason":"重复发放回收"}',"已驳回","60000004")]
    for aid,kd,tg,pl,st,by in APV:
        c.execute("INSERT INTO approval VALUES(?,?,?,?,?,?,?,?,?,?)",
          (aid,kd,tg,pl,st,by,"2026-08-30 15:20",
           "60000008" if st!="待审批" else None,
           "2026-08-31 09:10" if st!="待审批" else None,
           {"已通过":"核实无误,同意调整","已驳回":"缺少活动依据,退回补充","待审批":None}[st]))

    # ── 售后工单(状态取自设计稿的两条链;PRD 定其为外部主系统,本平台只读)──
    AS_REFUND=["待确认","审批同意","审批失败","退款失败","待结算","已完成"]
    AS_RETURN=["提交申请","审批同意","审批拒绝","商品寄回","已入库","退款成功","退款失败","已完成"]
    REASONS=["多拍/拍错/不想要","尺寸不合适","面料与描述不符","工艺瑕疵","交期延误","质量问题"]
    oids=[r[0] for r in c.execute("SELECT id FROM ordr ORDER BY id LIMIT 30")]
    for i in range(26):
        kind="仅退款" if i%2 else "退货退款"
        st=(AS_REFUND if kind=="仅退款" else AS_RETURN)[i%(6 if kind=="仅退款" else 8)]
        day=12+(i%18)
        c.execute("INSERT INTO aftersale VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (f"AS{64880127+i}",kind,oids[i%len(oids)],cust[i%len(cust)][0],st,
           REASONS[i%6],round(random.uniform(680,9600),2),random.choice(SHOPS),_adv_any(),
           f"2026-08-{day:02d} 09:{10+i%40:02d}",f"2026-08-{min(31,day+2):02d} 15:{10+i%40:02d}",
           "售后/维保系统",f"2026-09-01 0{i%9}:1{i%9}"))
    # ── 维保工单 ──
    MT=["待确认","取消","待入库","待处理","处理中","待签收","已完成"]
    ISSUES=["盘扣脱线","下摆开线","面料起球","刺绣局部脱落","拉链损坏","染色不均","尺寸需调整"]
    ITEMS=["云锦缠枝纹 唐制齐胸襦裙","苏绣缂丝 明制马面裙","素罗对襟 宋制褙子",
           "妆花缎 唐制大袖衫","缂丝团花 明制立领长衫"]
    # ⚠️ 这里原来是 `cust[(i+7)%len(cust)][0]` —— 客户号**按下标凑**,
    # 结果 21/21 条维修工单的客户号都和它所属订单的客户对不上(整体错位 7 位)。
    # 和 8 对「同一人」合并对里的性别/省份矛盾是**同一类错**:
    # **凡是「这条记录属于谁」,就必须从关联对象取,不能靠下标碰**。
    # 下标凑出来的关联在小数据上看不出来,数据一多就全错,而且不会报错。
    # item 同理:从订单真实的商品名取,这样才查得到它的面料与工艺 —— 判责要用。
    # 只挂**定制品订单** —— 判责要回头查这件的面料与工艺,标品查不到,
    # 而「西装套装盘扣脱线」这种现场本身就是假的。
    _cust_oids=[r[0] for r in c.execute(
        "SELECT id FROM ordr WHERE kind='定制品订单' ORDER BY id")] or oids
    # ── 按「每条规则至少一个用例」显式排,不用模运算撞 ────────────────
    # 之前靠 `ISSUES[(i+i//7*2)%7]` 凑分布,结果三条尺寸类工单的客户
    # **全是「到店且记录完整」**,于是返修判定表里
    # 「记录不全 → 我方免费改」和「远程量体 → 按合同分担」两行永远命中不了。
    #
    # 模运算能凑出**均匀**,凑不出**覆盖**。这两件事经常被当成一回事。
    # 下面这几条是照着客户的真实量体画像挑的(序号 = 定制单序号):
    #   5  → 记录完整且到店  → 客方收费改
    #   18 → 量体不足 4 项    → 我方免费改
    #   3  → 有远程量体      → 按合同分担
    #   7  → 特性类 + 无签收  → 我方让步
    #   10 → 特性类 + 有签收  → 无责解释
    FORCE = {5: ("尺寸需调整", "待确认"), 18: ("尺寸需调整", "待处理"),
             3: ("尺寸需调整", "处理中"), 7: ("面料起球", "待确认"),
             10: ("染色不均", "待处理"), 0: ("盘扣脱线", "处理中")}
    for i in range(21):
        _oid=_cust_oids[i%len(_cust_oids)]
        # 报修时间必须在**下单 → 交付 → 穿 → 报修**这条链的最后。
        # 原来 day 是独立编的,结果 13/21 条「报修早于订单创建」——
        # 衣服还没下单就来报修了。**模型读到这个现场直接拒绝判责,它是对的。**
        _ocr = c.execute("SELECT created FROM ordr WHERE id=?", (_oid,)).fetchone()[0][:10]
        _rep = date.fromisoformat(_ocr) + timedelta(days=18 + (i * 3) % 20)
        _own=c.execute("SELECT customer_id FROM ordr WHERE id=?",(_oid,)).fetchone()[0]
        _it=c.execute("SELECT name FROM ordr_item WHERE order_id=? LIMIT 1",(_oid,)).fetchone()
        c.execute("INSERT INTO maintain VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
          (f"MW{73020+i}",_oid,_own,(_it[0] if _it else ITEMS[i%5]),
           # ⚠️ 状态和问题原来都用 `i%7`,于是两者**完全相关** ——
           # 按状态筛出来的任何子集,问题必然是同一个值。
           # 结果「待确认/待处理/处理中」这 9 条判责工单全是「工艺瑕疵」一类,
           # **测试覆盖度被悄悄削成了 1/7,而且数据看起来完全正常**。
           # 让问题额外依赖 i//7,两个维度才真的独立。
           FORCE.get(i, (None, MT[i%7]))[1], FORCE.get(i, (ISSUES[(i+i//7*2)%7],))[0],
           random.choice(SHOPS),_adv_any(),
           f"{_rep.isoformat()} 11:{10+i%40:02d}",
           f"{(_rep+timedelta(days=3)).isoformat()} 16:{10+i%40:02d}",
           "售后/维保系统",f"2026-09-01 0{i%9}:2{i%9}"))

    # ── 交付告知签收 ──────────────────────────────────────────────────
    # **故意不是每单都有。** 三分之一的定制单没有签收记录 ——
    # 那正是「特性类但未书面告知 → 我方让步」这条规则要抓的现场。
    # 全都有签收的种子数据,等于把判责题的答案统一成了「无责」,那就不用判了。
    NOTICE=["N1 面料特性","N2 色差与掉色","N3 手工痕迹","N4 洗护方式","N5 尺寸容差","N6 工期与延期"]
    for i,_no in enumerate(_cust_oids):
        # 缺签收的挑 i%3==1 而不是 ==2:==2 时缺签收的那几单恰好都是工艺/尺寸类,
        # **而「有没有书面告知」只对特性类有意义** —— 结果「特性类未告知 → 我方让步」
        # 这条真值一个用例都没有,那条规则在评测里等于不存在。
        # 造数据时要盯的不是「分布均不均匀」,是「**每条规则有没有至少一个用例**」。
        # 再收窄一档:两条特性类工单(面料起球 / 染色不均)要**一条有告知、一条没有**,
        # 否则「已告知→无责」和「未告知→我方让步」总有一条拿不到用例。
        if i%3==1 and i%2==1: continue
        n=NOTICE if i%4 else NOTICE[:3]
        # 签收时间必须**在下单之后**。原来是独立编的日期,
        # 结果 15/20 条「交付签收早于订单创建」—— 衣服还没下单就签收了。
        _ocr = c.execute("SELECT created FROM ordr WHERE id=?", (_no,)).fetchone()[0][:10]
        _sign = (date.fromisoformat(_ocr) + timedelta(days=5 + i % 6)).isoformat()
        c.execute("INSERT INTO delivery_notice VALUES(?,?,?,?,?)",
                  (_no, ",".join(x.split()[0] for x in n),
                   f"{_sign} 17:{10+i%40:02d}",
                   _adv_any(), "门店纸质" if i%2 else "电子签"))

    # ── 库存变更日志(后台 PRD 第 8 章:关键写操作均可查询操作人、时间、前后值和业务编号)──
    KINDS=[("入库",1),("订单占用",-1),("订单释放",1),("退货入库",1),("盘点调整",0),("报损",-1)]
    skus=[r for r in c.execute("SELECT code,spu,stock FROM sku ORDER BY code")]
    ops=["60000001 张静静","60000004 周恒东","60000008 魏欣新","系统"]
    for i in range(60):
        sk=skus[i%len(skus)]
        kd,sign=KINDS[i%6]
        amt=random.randint(1,12)
        delta=amt*sign if sign else random.choice([-3,-2,2,3])
        before=max(0,sk[2]-delta*((i//len(skus))+1))
        after=max(0,before+delta)
        day=8+(i%22)
        c.execute("""INSERT INTO stock_log(sku,spu,kind,delta,before_n,after_n,ref,operator,ts,note)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (sk[0],sk[1],kd,delta,before,after,
           {"入库":"PO2608"+str(1000+i),"订单占用":"64880127"+str(19714560000+i%46),
            "订单释放":"64880127"+str(19714560000+i%46),"退货入库":"AS64880127"+str(i%26),
            "盘点调整":"CK2608"+str(100+i),"报损":"DM2608"+str(100+i)}[kd],
           random.choice(ops),f"2026-08-{day:02d} 1{i%9}:{10+i%45:02d}",
           {"盘点调整":"月度盘点差异修正","报损":"运输途中破损"}.get(kd,"")))

    # ── 汉服工艺 / 材质 / 形制知识库 ──
    # src_type:  public=公开来源可溯源  scale=公开资料量级  demo=演示数据(企业 know-how,无公开来源)
    # ── 负向评测专用数据(不进 task 表,由 agent/negative.py 单独出题)────────────
    # 双向测试原则:正向考「该做的做对」,负向考「不该做的没做」。
    # 负向题需要两种正向题里根本不存在的数据形态:一张没出问题的单、一张证据残缺的单。
    _cid = c.execute("SELECT id FROM customer LIMIT 1").fetchone()[0]
    # N1 健康单据:退款早已成功,压根没有失败可查
    c.execute("INSERT INTO deposit VALUES(?,?,?,?,?,?,?,?)",
              ("D9001", _cid, None, 600.0, "已退", "IDEM-D9001", "2026-08-05 10:00", "2026-08-05 10:07"))
    c.execute("INSERT INTO payment_flow VALUES(?,?,?,?,?,?,?,?)",
              ("PFD9001I", "D9001", "in", 600.0, "微信支付", "WX600100100100", "success", "2026-08-05 10:00"))
    c.execute("INSERT INTO payment_flow VALUES(?,?,?,?,?,?,?,?)",
              ("PFD9001O", "D9001", "out", 600.0, "微信支付", "WX600200200200", "success", "2026-08-05 10:07"))
    c.execute("INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key)"
              " VALUES(?,?,?,?,?,?,?,?)",
              ("D9001", 1, "2026-08-05 10:07", "微信支付", 600.0, "SUCCESS", "退款成功", "IDEM-D9001"))
    # N2 证据残缺:有失败轨迹,但支付流水一条都没有 —— 无法判断钱到底动没动
    c.execute("INSERT INTO deposit VALUES(?,?,?,?,?,?,?,?)",
              ("D9002", _cid, None, 1500.0, "退款失败", "IDEM-D9002", "2026-08-11 09:30", "2026-08-19 15:02"))
    for _a, _t in [(1, "2026-08-19 14:50"), (2, "2026-08-19 14:56"), (3, "2026-08-19 15:02")]:
        c.execute("INSERT INTO refund_trace(deposit_id,attempt,ts,channel,req_amount,resp_code,resp_msg,idem_key)"
                  " VALUES(?,?,?,?,?,?,?,?)",
                  ("D9002", _a, _t, "微信支付", 1500.0, "UNKNOWN", "渠道未返回明确结果", "IDEM-D9002"))

    # ── 员工登录凭据 ────────────────────────────────────────────────
    # ⚠️ **必须排在所有写 staff 的地方之后。** 第一版排在中间,
    # 而后面又插了 21 位工匠 —— 那批进了 staff 却**没有密码,登录不了**,
    # 而 staff 表上看起来完全正常(有工号、有姓名、有角色)。
    # **发凭据这类「给每个人补一份」的收尾动作要排在最后**,
    # 排在中间就只覆盖了那一刻已经存在的人。
    #
    # 这和「顾问引用回填排在中间漏了 238 条量体」是同一个形状 ——
    # 同一个错犯第二次了,所以这次把规则写在这儿。
    # 密码一律 PBKDF2 + 每人独立 salt,**明文一个字都不落库**(演示数据也不例外)。
    # 演示口令统一是 `lanxiu@2026`,写在这儿是因为它本来就是公开的演示密码;
    # 真上线时这段要换成「首次登录强制改密」。
    import hashlib as _hl, secrets as _sc
    _ITER = 120000
    DEMO_PW = "lanxiu@2026"
    for _st in c.execute("SELECT no,name FROM staff").fetchall():
        _no, _nm = _st
        _salt = _sc.token_hex(13)
        _hash = _hl.pbkdf2_hmac("sha256", DEMO_PW.encode(), bytes.fromhex(_salt), _ITER).hex()
        c.execute("UPDATE staff SET login_name=?,pwd_algo=?,pwd_salt=?,pwd_hash=? WHERE no=?",
                  (_no, f"pbkdf2_sha256${_ITER}", _salt, _hash, _no))

    # 形制表从 `01-形制.md` 派生 —— **`pattern.xz` 原来指向空处**。
    # ⚠️ **必须排在「定制方案」之前**:方案要把形制名换成编码,
    #    表还没建就查不到。顺序错了报的是「no such table」——
    #    而那句话看不出是顺序问题,看着像表没建。
    # 和别的推导器一样:md 是真相源,推导器算结论落库,检查对账。
    #
    # ⚠️ **用 seed 自己的连接,不起子进程。** 第一版 subprocess 调推导器,
    # 它开第二个连接,而 seed 的事务还开着 —— 拿到的是半截状态,当场失败。
    # 一个在事务中间被调用的脚本,不该自己去连库。
    sys.path.insert(0, os.path.join(HERE, "..", "knowledge"))
    import derive_xingzhi as _dx
    c.execute("""CREATE TABLE IF NOT EXISTS xingzhi(
        code TEXT PRIMARY KEY, name TEXT, alias TEXT, key_sizes TEXT, src_type TEXT)""")
    c.execute("DELETE FROM xingzhi")
    for _cd, _nm3, _al, _sz, _src in _dx.parse():
        c.execute("INSERT INTO xingzhi VALUES(?,?,?,?,?)",
                  (_cd, _nm3, _al, "、".join(_sz) or None, _src))

    # 定制方案:fe-scheme 状态机终于有承载物了(此前 PRD 定义了 4 状态 5 边,却没有任何页面)
    _cid2 = c.execute("SELECT id FROM customer LIMIT 1").fetchone()[0]
    for sid, nm, st, xz, mt, kf, col, ps in [
        ("SC2601","林女士婚服方案","已锁定","明制立领长衫","云锦","妆花,苏绣","胭脂","云肩,腰封"),
        ("SC2602","陈小姐日常款",  "已保存","宋制褙子",    "绫",  "平绣",     "竹青","发簪"),
        ("SC2603","写真三件套",    "草稿",  "唐制齐胸襦裙","真丝素罗","苏绣",  "月白","披帛"),
        ("SC2604","去年未成单",    "已失效","明制马面裙",  "织金缎","织金",    "玄色",""),
    ]:
        # **名字 → 编码,现查不手抄。** 手抄一份对照表就是第三个来源。
        # 查不到就**报错停住**,不写一个空值进去 ——
        # 一个 xz 为空的方案,在界面上和「还没选形制」长得一模一样。
        _xzc = c.execute("SELECT code FROM xingzhi WHERE name=?", (xz,)).fetchone()
        assert _xzc, f"方案 {sid} 的形制「{xz}」在形制表里查不到"
        _mtc = c.execute("SELECT code FROM material WHERE name=?", (mt,)).fetchone()
        assert _mtc, f"方案 {sid} 的面料「{mt}」在物料表里查不到"
        _kfc = []
        for _k3 in [x.strip() for x in kf.split(",") if x.strip()]:
            _r3 = c.execute("SELECT code FROM craft WHERE name=? AND cat!='形制'",
                            (_k3,)).fetchone()
            assert _r3, f"方案 {sid} 的工艺「{_k3}」在工艺表里查不到"
            _kfc.append(_r3[0])
        # **版型:一个形制下常有好几个,方案得落到具体那一个。**
        # 没指定变体就取标准款(命名约定:变体款都带后缀)——
        # 和商品匹配版型用的是同一条规则。
        _pt = c.execute("""SELECT code FROM pattern WHERE xz=?
                           ORDER BY (name LIKE '%标准%') DESC, code LIMIT 1""",
                        (_xzc[0],)).fetchone()
        assert _pt, f"形制 {_xzc[0]} 下没有版型,方案 {sid} 落不到具体版型"
        c.execute("INSERT INTO scheme(id,customer_id,name,status,xz,mt,kf,color,ps,"
                  "pattern,advisor,note,created,updated)"
                  " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (sid,_cid2,nm,st,_xzc[0],_mtc[0],",".join(_kfc),col,ps,
                   _pt[0],"A01 林岚",None,ago(20),ago(3)))

    # ── ③ 量体覆盖:让「本人」都有一套完整量体 ──────────────────────
    # 原来 104 个着装人只有 27 个有量体记录,而且每人只量了 5 或 9 项 ——
    # **14 个量体项没有一个人量全**。做上衣要通袖长、胸围、领围,
    # 只量了身高和裙长的话,推荐尺码那一步直接判「需补量」。
    #
    # 量体条件按 08 第四节记全:内搭 / 鞋 / 呼吸状态,**缺一件就等于没量**。
    _ITEMS = [r[0] for r in c.execute("SELECT code FROM measure_item ORDER BY code")]
    _BASE = {"MI01":165,"MI02":52,"MI03":86,"MI04":68,"MI05":92,"MI06":38,"MI07":56,
             "MI08":110,"MI09":98,"MI10":34,"MI11":26,"MI12":100,"MI13":80,"MI14":180}
    for _i, _w2 in enumerate(c.execute("""SELECT w.id, w.customer_id, w.gender, w.height
                                          FROM wearer w WHERE w.relation='本人'
                                            AND NOT EXISTS(SELECT 1 FROM measure_rec m
                                                           WHERE m.wearer_id=w.id)
                                          ORDER BY w.id""").fetchall()):
        _wid, _cid, _g, _h = _w2
        _d = (T - timedelta(days=20 + (_i * 13) % 300)).isoformat()
        _mth = "远程" if _i % 6 == 4 else "到店"
        _in, _sh = ["无","薄","厚"][_i % 3], ["赤足","平底","高跟"][_i % 3]
        for _it in _ITEMS:
            _base = _BASE.get(_it, 60) * ((_h or 165) / 165 if _it in ("MI01","MI08","MI09","MI12","MI14") else 1)
            c.execute("""INSERT INTO measure_rec(customer_id,tpl,item,value,measured_by,
                         measured_at,method,wearer_id,cond_inner,cond_shoe,cond_breath)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      (_cid, "MT01", _it, round(_base + ((_i * 7 + hash(_it) % 11) % 9) - 4, 1),
                       _adv_any(), f"{_d} 14:30", _mth, _wid,
                       _in, _sh, "平静呼气"))

    # ── 反例夹具:**故意留着的不完整数据** ──────────────────────────
    # ⚠️ 这一段看起来像脏数据,它不是。**不要好心把它补全。**
    #
    # 上面那个「给所有本人补齐 14 项量体」的改动,顺手把两类反例清零了:
    #   ① 判责规则「尺寸偏差 · 记录不全 · 我方免费改」从此没有任何用例;
    #   ② 靶身高与推算冲突「需人工确认」从此没有任何用例。
    # 没有用例的规则可以是错的,而且永远不会被发现 —— 反例在种子数据里是资产。
    #
    # ①:挑一个「到店量体 + 尺寸类在办工单」的客户,把量体删到 3 项。
    #    现实里这就是「量体没量完就下了单」,不罕见。
    _sp = c.execute("""SELECT m.customer_id FROM maintain m
                       WHERE m.issue='尺寸需调整' AND m.status IN ('待确认','待处理','处理中')
                         AND NOT EXISTS(SELECT 1 FROM measure_rec r
                                        WHERE r.customer_id=m.customer_id AND r.method='远程')
                       ORDER BY m.id DESC LIMIT 1""").fetchone()
    assert _sp, "没有「到店 + 尺寸类在办」的客户可做反例 —— 判责规则会缺用例"
    c.execute("""DELETE FROM measure_rec WHERE customer_id=? AND item NOT IN
                 (SELECT item FROM measure_rec WHERE customer_id=? ORDER BY item LIMIT 3)""",
              (_sp[0], _sp[0]))
    print(f"  [反例] {_sp[0]} 量体只留 3 项 —— 供「记录不全 · 我方免费改」用")

    # ②:挑一个父母俱全的孩子,把父母身高拉开,让**靶身高和百分位推算对不上**。
    #
    # ⚠️ **原来只钉了一半,所以它漂了两次。**
    #    原写法是把父母身高**写死 162/152**,指望中亲值 ~163 和百分位推算 ~176
    #    差 13cm。但差值是**两者之差**,而孩子那一边根本没钉 ——
    #    孩子的百分位推算来自他自己的量体身高,而量体是按下标生成的。
    #    新增一个版型(PT84)会让「商品由版型 × 相容矩阵长出来」那段多长几个商品,
    #    后面所有生成项的下标整体挪位,于是**孩子的推算身高从 176 掉到 170.3**,
    #    差值 6.8 < 门槛 8,**这条规则的唯一用例凭空消失**,
    #    而 `guards_test` 报的是「找不到满足条件的着装人」——
    #    看上去像夹具挑法的问题,其实是这个性质不存在了。
    #
    # **钉的应该是差值本身,不是其中一边。** 现在按孩子的实际推算身高倒推父母:
    # 让中亲值 = 推算 - 14,稳稳越过门槛 8,不管重播种怎么挪下标。
    # (试过父 192/母 150:中亲值 177.5 反而和推算 176.6 撞上了,gap 0.9。
    #  父母身高「差距大」不等于「和孩子对不上」—— 靶身高只看中亲值。)
    _kid = c.execute("""SELECT id, parent_a, parent_b FROM wearer
                        WHERE parent_a IS NOT NULL AND parent_b IS NOT NULL
                        ORDER BY id LIMIT 1""").fetchone()
    assert _kid, "没有父母俱全的孩子 —— 靶身高校验会缺用例"
    _ksex = c.execute("SELECT gender FROM wearer WHERE id=?", (_kid[0],)).fetchone()[0]
    # 先随便给个值,好让 forecast 跑得出「百分位推算成年身高」
    c.execute("UPDATE wearer SET height=170.0 WHERE id IN (?,?)", (_kid[1], _kid[2]))
    c.commit()
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
    import api as _api
    _fc = _api.forecast_growth(_kid[0], months=12)
    assert not _fc.get("error"), f"夹具孩子推不出成长曲线:{_fc.get('error')}"
    _pred = _fc["靶身高校验"]["百分位推算成年身高"]
    # 中亲值 = (父 + 母 + 13男 / -13女) / 2,要它等于 _pred - 14
    _want_mid = _pred - 14
    _sum = _want_mid * 2 - (13 if _ksex == "男" else -13)
    _fa, _mo = round(_sum / 2 + 5, 1), round(_sum / 2 - 5, 1)
    c.execute("UPDATE wearer SET height=? WHERE id=?", (_fa, _kid[1]))
    c.execute("UPDATE wearer SET height=? WHERE id=?", (_mo, _kid[2]))
    c.commit()
    # **要求什么就断言什么** —— 上面算得再对,也要真跑一遍确认它真的冲突了。
    _fc2 = _api.forecast_growth(_kid[0], months=12)
    assert _fc2["靶身高校验"]["需人工确认"], (
        f"靶身高冲突夹具没立住:差值 {_fc2['靶身高校验'].get('差值')} "
        f"没过门槛 —— 「需人工确认」这条规则会缺用例")
    # ③:把一条在制工单的交期设成过去 —— 否则 get_workorder 的「已逾期」
    #    这条规则**永远不会被触发**,它错了也没人知道(和上面两条同病)。
    #    现实里逾期工单当然存在,而且正是排产最该先看的那一类。
    _wo = c.execute("SELECT id FROM workorder WHERE status='在制' ORDER BY id LIMIT 1").fetchone()
    assert _wo, "没有在制工单可做反例 —— get_workorder 的逾期分支会缺用例"
    c.execute("UPDATE workorder SET due_date=? WHERE id=?",
              ((T - timedelta(days=6)).isoformat(), _wo[0]))
    print(f"  [反例] {_wo[0]} 交期设为 6 天前 —— 供「已逾期」用")

    print(f"  [反例] {_kid[0]} 的父母身高设为 {_fa}/{_mo}(按他的推算身高 {_pred} 倒推,"
          f"差值 {_fc2['靶身高校验']['差值']})—— 供「靶身高冲突需人工确认」用")

    # ── BP-03 售后判责:研判工单 + 人工标注真值 ────────────────────────
    # 只挑**还没处理完**的(待确认 / 待处理 / 处理中)—— 已完成和取消的不用判。
    #
    # ⚠️ 这里的标注是**在种子里显式写出来的一套判断**,
    # 而 knowledge/liability.py 是**从 09-养护与售后.md 第五节独立解析出来的另一套**。
    # 两条实现,同一份文档 —— 对不上就说明有一边错了,
    # backend/liability_check.py 每次都会对账。
    # **拿被测系统自己算出来的期望值,只能抓数据漂移,抓不到实现错误。**
    _CRAFT = ("盘扣脱线", "下摆开线", "刺绣局部脱落", "拉链损坏")
    _SIZE  = ("尺寸需调整",)
    for m in c.execute("""SELECT id, order_id, customer_id, item, issue, status
                          FROM maintain WHERE status IN ('待确认','待处理','处理中')
                          ORDER BY id""").fetchall():
        mid, oid, cid, item, issue, st = m
        notified = c.execute("SELECT 1 FROM delivery_notice WHERE order_id=?", (oid,)).fetchone()
        remote = c.execute("SELECT 1 FROM measure_rec WHERE customer_id=? AND method='远程'",
                           (cid,)).fetchone()
        n_meas = c.execute("SELECT count(*) FROM measure_rec WHERE customer_id=?",
                           (cid,)).fetchone()[0]
        if issue in _CRAFT:
            rc = "工艺瑕疵 · 我方免费返修"
            act = "免费返修,不向客户收费"
            ev = f"「{issue}」属工艺瑕疵(09 第五节第 1 行)"
        elif issue in _SIZE:
            if remote:
                rc, act = "远程量体偏差 · 按合同分担", "按合同约定分担返修费用"
                ev = "该客户量体方式含「远程」,09 第五节第 4 行优先于记录是否完整"
            elif n_meas >= 4:
                rc, act = "尺寸偏差 · 记录完整 · 客方收费改", "收费改,出示量体记录"
                ev = f"到店量体 {n_meas} 项,记录完整且相符(09 第五节第 2 行)"
            else:
                rc, act = "尺寸偏差 · 记录不全 · 我方免费改", "免费改"
                ev = f"量体记录只有 {n_meas} 项,不完整(09 第五节第 3 行)"
        else:
            if notified:
                rc, act = "特性类已告知 · 无责解释", "解释 + 提供保养服务,不返修不赔付"
                ev = "交付时有书面告知签收记录(09 第五节第 6 行)"
            else:
                rc, act = "特性类未告知 · 我方让步", "让步处理"
                ev = "**没有交付告知签收记录**,特性类未书面告知(09 第五节第 7 行)"
        c.execute("INSERT INTO task VALUES(?,?,?,?,?,?)",
                  (f"T{mid}", "售后判责", mid, "待处理", "2026-08-25", f"{item} · {issue}"))
        truths.append((mid, "BP-03", rc, act, ev, f"{item} · {issue} · 工单状态 {st}"))

    # ── ④ 成长推算留档 ──────────────────────────────────────────────
    # 表建了却一行没写,等于没建。它存的**不是结果,是当时怎么推的**:
    # 依据哪次量体、用了哪个方法、给了多宽的区间。
    # 事后客户说「你们说能穿到明年」,得查得出当时到底说了什么。
    #
    # 留档写在**运维侧**,不写在工具层 —— 工具层是只读的,那是本项目最硬的一条主张。
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge"))
    import growth as _gr
    _fc = 0
    for _w3 in c.execute("""SELECT w.id, w.gender, w.birthday FROM wearer w
                            WHERE w.relation IN ('子','女') AND w.birthday IS NOT NULL
                            ORDER BY w.id""").fetchall():
        _wid, _g3, _bd = _w3
        _h3 = c.execute("""SELECT value, measured_at FROM measure_rec
                           WHERE wearer_id=? AND item='MI01'
                           ORDER BY measured_at DESC LIMIT 1""", (_wid,)).fetchone()
        if not _h3: continue
        for _m in (6, 12):
            _tgt = (T + timedelta(days=int(30.4 * _m))).isoformat()
            try:
                _r3 = _gr.forecast(_g3, _bd, _h3[0], _h3[1][:10], _tgt)
            except Exception:
                continue
            c.execute("""INSERT INTO growth_forecast(wearer_id,base_at,base_height,base_z,
                         method,target_at,pred_height,lo,hi,note,created)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                      (_wid, _h3[1][:10], _h3[0], _r3["z分数"], _r3["方法"], _tgt,
                       _r3["预测身高"], _r3["区间"][0], _r3["区间"][1],
                       " / ".join(_r3["限定"][:2]), T.isoformat()))
            _fc += 1

    # ── 体型特征(放在最后:要等所有着装人都建完)────────────────────
    # 挂到**具体的着装人**上 —— 而且只挂成年人:
    # 溜肩/含胸/高低肩/腹凸这几种是成人体型问题,给 3 岁孩子记「腹凸」是假数据。
    _adults = [r[0] for r in c.execute("""SELECT id FROM wearer
                 WHERE relation IN ('本人','配偶') ORDER BY id""")]
    for k,wid in enumerate(_adults):
        if k % 9: continue                       # 九分之一的人有明显体型特征
        f,note=FEAT[(k//9)%4]
        c.execute("INSERT INTO body_feature VALUES(?,?,?,?,?)",
                  (wid,f,note,_adv_any(),f"2026-0{6+k%3}-1{k%9} 14:40"))

    # ── C3:把时间锚点理顺(放在最后,等所有对象都建完)────────────────
    # ① 客户建档不得晚于他最早的业务事件 —— **人还没建档就下了单**,是不可能的。
    #    往前拉建档日期,而不是往后推订单 —— 订单日期牵着一整条时间链。
    for _cid, _first in c.execute("""
            SELECT k.id, MIN(x.d) FROM customer k JOIN (
                SELECT customer_id cid, created d FROM ordr
                UNION ALL SELECT customer_id, created FROM deposit
                UNION ALL SELECT customer_id, start_ts FROM appointment
                UNION ALL SELECT customer_id, start_ts FROM schedule
                -- 量体也是业务事件 —— 漏了它,14 条量体记录就会早于客户建档。
                -- **「最早业务事件」这个集合少列一项,那一项就永远查不出来。**
                UNION ALL SELECT customer_id, measured_at FROM measure_rec
                UNION ALL SELECT customer_id, created FROM maintain
            ) x ON x.cid = k.id
            WHERE x.d IS NOT NULL GROUP BY k.id""").fetchall():
        if _first and _first[:10] < (c.execute("SELECT created FROM customer WHERE id=?",
                                               (_cid,)).fetchone()[0] or "9999")[:10]:
            c.execute("UPDATE customer SET created=? WHERE id=?",
                      ((date.fromisoformat(_first[:10]) - timedelta(days=3)).isoformat(), _cid))
    # ② 账户不得晚于它名下最早的门店档案 —— 账户是在第一次建档时开出来的
    c.execute("""UPDATE account SET created = COALESCE(
                   (SELECT MIN(k.created) FROM customer k WHERE k.account_id = account.id),
                   created)""")

    # ── B4:工单 ref 统一回填 ────────────────────────────────────────
    # 工坊工单在订单之前播种,所以播种时取不到订单 —— 懒查也救不了,
    # 因为那时订单表就是空的。**顺序依赖治不好,就别治,挪到最后统一回填。**
    # 一单可以有多道工序(织造/印染/刺绣/缝制),多对一是对的。
    _co = [r[0] for r in c.execute("SELECT id FROM ordr WHERE kind='定制品订单' ORDER BY id")]
    if _co:
        for _n, _wo in enumerate(r[0] for r in c.execute("SELECT id FROM workorder ORDER BY id")):
            c.execute("UPDATE workorder SET ref=? WHERE id=?", (_co[_n % len(_co)], _wo))

    # ── 下单前置规则的不变量 ────────────────────────────────────
    # 量体日期上面是按序号生成的(`f"2026-0{6+k%3}-1{k%9}"`),
    # **既不看着装人年龄,也不看下单日期** —— 于是会生出两种坏数据:
    # 量体比订单还晚、孩子的量体停在半年多以前(复量周期对未成年是 180/120 天)。
    #
    # 这里统一收一遍。逻辑在 `fix_order_measure.py`,**老库迁移也调它** ——
    # 一份代码两个调用方,新库老库两条路都对。
    #
    # ⚠️ 它**故意留一个不修**(刘星野,量体过期 272 天)——
    # 和上面那段反例夹具同一个道理:**没有用例的规则可以是错的,
    # 而且永远不会被发现。** 全修干净的话「超期量体不许下单」一个用例都没有。
    # 积分中间余额:生成时被 max(0,...) 截断过,这里统一重算一遍。
    # **和老库迁移(tools/migrate_points_balance.py)用同一个算法** ——
    # 第一版只写了迁移脚本,于是新灌的库照样有 30 处断点,
    # 而检查在我这台机器上是绿的(因为我迁移过)。
    _pl = {}
    for _cid2, in c.execute("SELECT DISTINCT customer_id FROM points_log"):
        _rows = list(c.execute("SELECT rowid,delta,balance FROM points_log "
                               "WHERE customer_id=? ORDER BY ts,rowid", (_cid2,)))
        if not _rows: continue
        _bal = _rows[-1][2]
        _new = [0] * len(_rows); _new[-1] = _bal
        for _k2 in range(len(_rows) - 2, -1, -1):
            _new[_k2] = _new[_k2 + 1] - _rows[_k2 + 1][1]
        for _r2, _b2 in zip(_rows, _new):
            if _r2[2] != _b2:
                c.execute("UPDATE points_log SET balance=? WHERE rowid=?", (_b2, _r2[0]))

    # 商品→版型这条边,以及从版型派生的性别/量体模板。
    # **补这条边之前,86 个有版型的定制品里 66 个模板是错的** ——
    # 长衫按裙子的口径量、罩甲按裙子的口径量、云肩和团扇也挂着长衫模版。
    # 商品上原来没有 pattern 列,性别和模板只能各填一遍,**重填就会错**。
    # ── 版型挂错模板的,挂回去 ────────────────────────────────
    # `xingzhi_check` 抓的:关键尺寸要腰围/胸上围,而模板是「上衣用量体」。
    # **改模板会让「上衣用量体」不再是上衣用量体**,所以改的是版型。
    for _pt, _want, _why in (
            ("XZ37", "LT02", "改良汉元素连衣裙要腰围 —— 连衣裙用裙装模版,不用上衣模版"),
            ("XZ14", "LT01", "宋制抹胸要胸上围(决定裙头位置)—— 唐装模版才有这一项")):
        _n5 = c.execute("UPDATE pattern SET tpl=? WHERE xz=? AND tpl!=?",
                        (_want, _pt, _want)).rowcount
        if _n5:
            print(f"  [版型换模板] {_pt} 的 {_n5} 个版型 → {_want}({_why})")


    import fix_product_pattern as _fpp
    _fpp.link(c); _fpp.derive(c); _fpp.recat(c)

    # ── 亲子装的两行要落在**同一张单**上 ─────────────────────────────
    # 拆成两个 SPU 之后,两张订单各自独立生成,于是「一家人一起订」这件事
    # 在数据里根本看不出来 —— 而**亲子的全部意义就是一次买两件给两个人**。
    # 更具体地:拆之前那张单只有一行、一个着装人(9 岁的王清和),
    # **大人那一件根本不在单上**;拆之后变成两张单各一行,还是表达不出「一起买的」。
    #
    # 把童款那一行并到大人款所在的单上。**排在 assign_item_wearers 之前** ——
    # 着装人是后面按商品性别匹配的,行先到位,人才匹配得上
    # (「收尾动作要排在最后」的另一面:**产生行的动作要排在最前**)。
    _cp = [r[0] for r in c.execute(
        "SELECT spu FROM product WHERE name LIKE '「同心」亲子%' ORDER BY name")]
    if len(_cp) == 2:
        _adult = c.execute(
            "SELECT p.spu,i.order_id FROM ordr_item i JOIN product p ON p.spu=i.spu "
            "WHERE i.spu IN (?,?) AND p.gender='女'", tuple(_cp)).fetchone()
        _kid = c.execute(
            "SELECT i.id,i.order_id FROM ordr_item i JOIN product p ON p.spu=i.spu "
            "WHERE i.spu IN (?,?) AND p.gender='童'", tuple(_cp)).fetchone()
        if _adult and _kid and _adult[1] != _kid[1]:
            _old = _kid[1]
            c.execute("UPDATE ordr_item SET order_id=? WHERE id=?", (_adult[1], _kid[0]))
            # 金额跟着搬 —— 一行换了单,两张单的金额都要重算。
            # ⚠️ **三个字段是三个口径,不许拿同一个数去填**(我第一版就这么干的):
            #   goods_amount = Σ 基本金额     (不含定制部件)
            #   amount       = Σ 合计 + 运费  (含定制部件)
            #   payable      = 应付,跟 amount 走
            # 拿 Σ合计 同时填 goods_amount,`member_order_check` 的金额勾稽当场红两条。
            for _oid in (_adult[1], _old):
                _g, _t = c.execute(
                    "SELECT COALESCE(SUM(base_amount),0), COALESCE(SUM(total),0) "
                    "FROM ordr_item WHERE order_id=?", (_oid,)).fetchone()
                _fr = (c.execute("SELECT freight FROM ordr WHERE id=?",
                                 (_oid,)).fetchone() or [0])[0] or 0
                c.execute("UPDATE ordr SET goods_amount=?, amount=?, payable=? "
                          "WHERE id=?", (round(_g, 2), round(_t + _fr, 2),
                                         round(_t + _fr, 2), _oid))
            # 并走之后空了的那张单没有任何行 —— **空单和「还没下单」长得一样**,删掉
            c.execute("DELETE FROM ordr WHERE id=? AND NOT EXISTS"
                      "(SELECT 1 FROM ordr_item WHERE order_id=?)", (_old, _old))
            print(f"  [亲子装] 童款那一行并进大人款所在的单 {_adult[1]}")

    import fix_order_measure as _fx
    _fx.ensure_wearers(c)              # 名下没有对得上的人 → 建档 + 量体
    _fx.assign_item_wearers(c)         # 行级:商品性别说得出来是给谁做的
    _, _, _kept_row = _fx.enforce_rows(c)   # 行级:被匹配上就必须有有效量体
    c.execute("UPDATE ordr SET wearer_id=NULL")   # 判据换过,旧值要清
    _fx.assign_wearers(c)              # 订单级:整单只给一个人时也填上
    _n_fix, _kept_ord = _fx.enforce(c, verbose=False)
    # **两层任一层留住夹具都算数。** 亲子装拆开之后这条反例只在行级存在
    # (整单两个着装人 → 订单级判不了 → 那一层看不见它),
    # 而订单级的认定还留着,因为别的单可能只有一个着装人。
    _kept = _kept_row or _kept_ord

    # 顾问引用:七张表存着「A04 陆微」这种字符串,补上指向工号的列。
    # **名字一改,所有历史记录当场断掉而且悄无声息** ——
    # 而 `schedule` 已经把结论摆在那儿了:它同时有名字和工号,
    # 而「一个人两套编号」那个 bug 就是从这儿来的。
    #
    # ⚠️ **必须排在所有写 measure_rec 的地方之后。** 第一版排在前面,
    # 而 `ensure_wearers` 之后又插了 238 条量体 —— 那批没有工号,
    # 检查报「有名字的行没补上工号」。**回填这类收尾动作要排在最后**,
    # 排在中间就只覆盖了那一刻已经存在的行。
    import fix_advisor_ref as _far
    _far.link(c)
    print(f"  [下单前置] 挪了 {_n_fix} 条超期量体;"
          f"留 1 条反例夹具({_fx.夹具说明})")
    assert _kept, "反例夹具丢了 —— 「超期量体不许下单」这条规则会没有用例"

    c.executemany("INSERT INTO truth(case_id,breakpoint,root_cause,expected_action,expected_evidence,note) VALUES(?,?,?,?,?,?)", truths)
    c.commit()
    print(f"已生成 {DB}")
    for t,label in [("customer","客户"),("deposit","押金"),("refund_trace","退款轨迹"),
                    ("payment_flow","支付流水"),("appointment","预约"),("followup","跟进"),
                    ("task","人工任务"),("truth","标注真因")]:
        print(f"  {label:8s} {c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:4d}")
    print("\n真因分布:")
    for bp,cause,cnt in c.execute("SELECT breakpoint,root_cause,COUNT(*) FROM truth GROUP BY breakpoint,root_cause"):
        print(f"  [{bp}] {cause:16s} {cnt}")
    c.close()

if __name__=="__main__": run()
