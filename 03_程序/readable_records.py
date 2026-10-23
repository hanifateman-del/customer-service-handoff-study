"""把程序记录整理成供团队阅读的中文说明，不改动实验数据。"""
import json
from datetime import datetime, timezone, timedelta
import os
import hashlib
from collections import Counter


def readable_time(value):
    if not value:
        return "见程序记录"
    try:
        return datetime.fromisoformat(value).strftime("%Y年%m月%d日 %H:%M:%S（北京时间）")
    except ValueError:
        return value


def review_markdown(reviews, title="待检查的对话"):
    lines = [f"# {title}", "", f"这里有{len(reviews)}段程序抽出的对话，还需要人工判断是否适合实验。每段只显示截取位置之前的原文。", "",
             "先看用户想办什么，再找还有什么没办完。每个判断都记下原文编号，拿不准就写原因。原文编号从0开始，与程序中的编号一致。", "",
             "原始记录中的分词空格保留。每段的编号可用来对应 JSON 文件。", ""]
    for i, item in enumerate(reviews, 1):
        lines += [f"## 第{i}段：对话 {item['dialogue_id']}", "",
                  f"对应编号：{item['review_id']}。截到第{item['cut_after_index']}句，下面不显示后面的对话。", ""]
        for u in item["prefix"]:
            speaker = "顾客" if u["speaker"] == "Q" else "客服"
            lines += [f"**第{u['utterance_index']}句 · {speaker}：** {u['utterance']}", ""]
    return "\n".join(lines)


def annotation_markdown(reviews):
    lines = [f"# 这{len(reviews)}段对话的人工标注表", "", "请先看同文件夹里的《标注怎么填》。两个人独立填写时各存一份，讨论后的版本也另存。标注是否完成以实际填写内容为准。", "",
             "这里只放截取前的对话。用户想办的每件事分开记；每件都写完成标准、当前状态和依据。完成中文表后，还需要整理到 JSON 工作副本，二者不会自动同步。", ""]
    for i, item in enumerate(reviews, 1):
        lines += [f"## 第{i}段：对话 {item['dialogue_id']}", "", f"对应编号：{item['review_id']}；截至第{item['cut_after_index']}句。", ""]
        for u in item["prefix"]:
            speaker = "顾客" if u["speaker"] == "Q" else "客服"
            lines += [f"第{u['utterance_index']}句（{speaker}）：{u['utterance']}", ""]
        lines += ["### 在这里填写", "", "填写人：", "", "这个交接位置合不合适，为什么：", "",
                  "用户想办的事（多件事分开写）：", "", "每件事怎样才算办完：", "",
                  "每件事当前的状态（还没办完／已经办完／看不出来）：", "", "原文依据及句子编号：", "",
                  "这段能不能纳入实验（可以／不可以／暂时不能确定），原因：", ""]
    return "\n".join(lines)


def project_root(path):
    for p in (path, *path.parents):
        if (p / "01_研究说明").is_dir() and (p / "03_程序").is_dir():
            return p
    return None


def link_from(folder, target):
    return os.path.relpath(target, folder).replace("\\", "/")


def write_run_summary(out, record):
    """按当次参数写说明，失败、筛选和样本导出分别叙述。"""
    root = project_root(out)
    params = record.get("parameters", {})
    status = {"completed": "已完成", "failed": "未完成", "running": "运行中"}.get(record.get("status"), "见原始记录")
    kind = record.get("kind", "screen" if (out / "screen_report.json").is_file() else "未知")
    kind_name = {"screen": "数据筛选", "finalize": "人工确认后的样本导出"}.get(kind, kind)
    lines = [f"# {out.name}", "", f"这次做的是：{kind_name}。状态：{status}。", "", f"开始时间：{readable_time(record.get('started_at'))}。", ""]
    if root:
        lines += [f"当前运行方法见 [程序运行说明]({link_from(out, root / '03_程序/运行说明.md')})，目录位置见 [项目入口]({link_from(out, root / 'README.md')})。", ""]
    if record.get("status") == "failed":
        error = record.get("error", "")
        lines += ["## 为什么没有完成？", ""]
        if "FileNotFoundError" in error and "work" in error:
            lines += ["这次命令仍指向整理前的 work 文件夹，因此没有找到标注文件。当前工作文件放在05_人工标注。", "", "现在在项目根目录使用 `python .\\csds_screen.py finalize --n 10`，即可读取当前默认位置；先完成标注，确认合格数量足够后再导出。", ""]
        elif "少于要求" in error:
            lines += ["人工确认合格的对话数量还不够，程序没有重复凑数。请先完成标注或增加复核量，再用新输出目录导出。", ""]
        else:
            lines += ["程序未能完成。具体错误原文保存在 run_record.json 的 error 字段和 logs/console.log 中。修正原因后使用新输出目录重试。", ""]
        lines += ["这份失败记录不代表已经生成可用于摘要实验的样本。", ""]
    elif kind == "screen" and (out / "screen_report.json").is_file():
        report = json.loads((out / "screen_report.json").read_text(encoding="utf-8"))
        c, rules = report["counts"], report["rules"]
        blocks = rules.get("agent_blocks_after_first_topic_hit", params.get("agent_blocks", 2))
        minimum = rules.get("min_prefix_messages", params.get("min_messages", 4))
        audit_limit = params.get("audit_prefix_messages", 12)
        lines += ["## 用了什么、怎样筛？", "", f"输入共{c['input_records']:,}段，咨询方是消费者的有{c['customer_records']:,}段。输入来源和文件校验值见 [筛选统计](screen_report.json)。", "",
                  f"先在顾客发言中寻找售后关键词。第一次命中后，数到第{blocks}个客服连续发言块结束时截断，材料从对话开头保留。至少保留{minimum}条发言，截止点不能是整段结尾。", "",
                  "本次精确词表和参数见 [规则参数](rules/rules.json)，[文字规则](rules/rule_explanation.md) 保存当时的判断办法。", "",
                  "## 筛选结果", "", "| 结果 | 数量 |", "| --- | ---: |"]
        labels = {"candidate_needs_human_review": "候选，仍需人工确认", "no_customer_topic_hit": "消费者发言未命中词表", "qrole_not_customer": "咨询方不是消费者", "cut_at_dialogue_end": "截止点已到整段结尾", "insufficient_agent_blocks": "售后话题后的客服回复块不足", "prefix_too_short": "截取后发言太少", "duplicate_dialogue": "重复对话", "invalid_dialogue": "对话格式不符合要求"}
        for key, label in labels.items():
            if key in c:
                lines.append(f"| {label} | {c[key]:,} |")
        lines += ["", f"随机抽取{report['review_sample_n']}段供人工检查，见 [本次待检查对话](review_batch.md)。另抽{report['excluded_audit_n']}段排除记录，每段最多显示前{audit_limit}句，供检查漏筛表达。", "",
                  f"规则版本：{report['version']}；随机种子：{rules['seed']}。候选数量不等于存在未决事项的数量；同一数据、规则和种子的重复运行也不构成独立样本。", ""]
        if root:
            lines += [f"下一步按 [标注方法]({link_from(out, root / '05_人工标注/标注怎么填.md')}) 检查原文。现有工作表对应哪次抽样，见 [标注目录]({link_from(out, root / '05_人工标注/README.md')})；不要把本次对话直接填进不对应的表。", ""]
    elif kind == "finalize" and (out / "selection_report.json").is_file():
        selected = json.loads((out / "selection_report.json").read_text(encoding="utf-8"))
        lines += [f"人工确认合格{selected['accepted_n']}段，本次选出{selected['selected_n']}段。", "", "model_inputs.jsonl 是摘要模型输入；gold_unresolved.jsonl 是人工参考答案，不给模型提前看。完整人工判断保存在 inputs/human_reviews.json。", ""]
    if record.get("record_type") == "backfilled_after_execution":
        lines += ["这次运行结束后才补建记录，没有确切起止时间，未补造。", ""]
    lines += ["## 怎样理解这里的旧路径？", "", "run_record.json、日志、规则参数和代码副本保留当时实际使用的内容。其中的旧路径用于追溯过去，不是当前操作步骤。重新运行请使用当前项目入口，不要照抄历史参数中的旧目录。", "",
              "本文件是按原始记录整理的阅读说明，数据、样本名单和当次规则不因文字更新而改变。", ""]
    (out / "实验记录.md").write_text("\n".join(lines), encoding="utf-8")


def refresh_project_indexes(root):
    """根据现有运行和标注文件更新目录表，避免固定的运行次数过时。"""
    runs = []
    for folder in (root / "04_实验记录").iterdir():
        path = folder / "run_record.json"
        if folder.is_dir() and path.is_file():
            record = json.loads(path.read_text(encoding="utf-8"))
            kind = record.get("kind", "screen" if (folder / "screen_report.json").is_file() else "未知")
            runs.append((folder, record, kind))
    runs.sort(key=lambda x: (x[1].get("started_at") or "", x[0].name))
    now = readable_time(datetime.now(timezone(timedelta(hours=8))).isoformat())
    lines = ["# 实验记录目录", "", f"更新于{now}。本表按各目录的 run_record.json 自动整理。", "", "每个子文件夹代表一次运行，失败也保留。点击记录查看目的、参数、结果和后续步骤。", "",
             "| 目录 | 做了什么 | 状态 | 候选／导出数量 | 阅读入口 |", "| --- | --- | --- | --- | --- |"]
    review_groups = {}
    counts = Counter()
    for folder, record, kind in runs:
        state = record.get("status", "未知")
        counts[(kind, state)] += 1
        number = "—"
        if kind == "screen" and (folder / "screen_report.json").is_file():
            report = json.loads((folder / "screen_report.json").read_text(encoding="utf-8"))
            number = str(report["counts"].get("candidate_needs_human_review", 0)) + "段候选"
        elif (folder / "selection_report.json").is_file():
            report = json.loads((folder / "selection_report.json").read_text(encoding="utf-8"))
            number = str(report["selected_n"]) + "段导出"
        label = {"screen": "筛选", "finalize": "样本导出"}.get(kind, kind)
        state_label = {"completed": "完成", "failed": "失败", "running": "运行中"}.get(state, state)
        lines.append(f"| {folder.name} | {label} | {state_label} | {number} | [记录]({folder.name}/实验记录.md) |")
        batch = folder / "review_batch.json"
        if state == "completed" and batch.is_file():
            ids = [x["review_id"] for x in json.loads(batch.read_text(encoding="utf-8"))]
            key = hashlib.sha256(json.dumps(ids, ensure_ascii=False).encode("utf-8")).hexdigest()
            review_groups.setdefault(key, []).append(folder.name)
    lines += ["", "## 哪些运行抽到了同一批？", ""]
    for group in review_groups.values():
        if len(group) > 1:
            lines += ["以下目录的待检查对话编号及顺序相同：" + "、".join(group) + "。这些是复跑记录，不能累加为独立样本。", ""]
    lines += ["当前人工工作表的对应关系见 [05_人工标注](../05_人工标注/README.md)。用于检查代码和路径的技术核对在 [06_修改历史](../06_修改历史/README.md)，不列作新的独立研究。", "",
              "重新执行的正确命令见 [运行说明](../03_程序/运行说明.md)。历史日志和代码里的旧路径只表示当时情况。", ""]
    (root / "04_实验记录/README.md").write_text("\n".join(lines), encoding="utf-8")
    status = ["# 当前项目状态", "", f"更新于{now}；这是一份文件状态快照。", "",
              f"04_实验记录内已完成筛选{counts[('screen', 'completed')]}次，成功样本导出{counts[('finalize', 'completed')]}次，失败运行{sum(n for (k, s), n in counts.items() if s == 'failed')}次。详细记录见 [运行目录](04_实验记录/README.md)。", ""]
    work = root / "05_人工标注/annotations_pilot_v0.2.json"
    if work.is_file():
        try:
            reviews = json.loads(work.read_text(encoding="utf-8-sig"))
            states = Counter(x.get("review", {}).get("eligibility", "unreviewed") for x in reviews)
            status += [f"程序用的 JSON 工作副本有{len(reviews)}段：尚未检查{states['unreviewed']}段、可纳入{states['eligible']}段、不可纳入{states['ineligible']}段、暂不能判断{states['uncertain']}段。中文表的填写进度可能尚未同步，阅读时请区分两者。", ""]
        except (ValueError, TypeError, AttributeError):
            status += ["JSON 工作副本目前无法读取，请先检查文件是否保存完整。", ""]
    status += ["程序目前支持筛选和人工确认后的样本导出。写 A/B 摘要、人工评分和统计分析仍是后续步骤；本状态页不会把筛选候选当作人工确认结果。", "",
               "每次在04_实验记录的直接子目录运行后自动更新本页。手动修改标注或外部复制运行目录后，可在项目根目录执行 `.\\运行项目.ps1 -Action docs` 更新状态和目录表。", "",
               "[返回项目入口](README.md)", ""]
    (root / "当前状态.md").write_text("\n".join(status), encoding="utf-8")
