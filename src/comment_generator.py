"""Agent Platform（旧Vertex AI）経由でGeminiを呼び出し、日次フィードバックを生成する。

出力はOKR＋SBI＋KPTのハイブリッド形式:
- O (Objective): 施策全体の目標。被験者ごとの数値目標を保持する仕組みが無いため、
  settings.objective_text の固定文をそのまま使う（Geminiには生成させない。契約上
  一定の文言であるべきものをLLMに都度言い換えさせると表記が揺れるため）。
- KR (Key Results): 当日フラグが立った指標（metrics.compute_flagsのSD逸脱判定）のみを
  対象にする。全11指標を毎日展開すると長大になり、トレーナーが読む分量として実用的でない。
- KR毎に、トレーナー向けの客観的分析(SBI)と、ゲストへそのまま伝える口語メッセージ(KPT)を
  分離して生成する。SBIは「事象の分析」、KPTは「伝達するメッセージ」という役割分担とし、
  内容が重複しないようSYSTEM_PROMPTで明示する。
フラグが立った指標が無い日はGeminiを呼ばず、固定の激励文を返す（コスト削減、かつ
「特筆すべき逸脱なし」は判定ロジック側で確定済みのため生成の余地が無い）。

Geminiは純正のGoogleモデルのため、API（aiplatform.googleapis.com）を有効化するだけで
利用できる（Model Garden経由のパートナーモデルのような追加の利用規約同意が不要）。
"""

import hashlib
import json
import logging

import pandas as pd
from google import genai
from google.genai import types

from src.config import TIME_METRICS, TOTAL_SLEEP_COLUMN, Settings

logger = logging.getLogger(__name__)

# フラグが立った指標が無い日に返す固定文（Gemini呼び出し無し）
NO_FLAG_COMMENT = "本日は特に大きな逸脱は見られません。引き続き今の生活リズムを維持しましょう。"

# response_mime_type="application/json"だけだとGeminiが構造を厳密に守らず、
# (実測: kptをsbiオブジェクトの内側にネストして返す等) 稀に階層を誤ることがあったため、
# response_schemaで構造を強制する。
# 注意: response_schemaに素のdict(JSON Schema風)を渡す方式は、この検証時点では
# Vertex AI側に構造を守らせられず同じ問題が再現した。types.Schemaオブジェクトを
# 明示的に構築する方式でのみ確実に効いたため、こちらを使う
_STR = types.Schema(type=types.Type.STRING)
_SBI_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={"situation": _STR, "behavior": _STR, "impact": _STR},
    required=["situation", "behavior", "impact"],
)
_KPT_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={"keep": _STR, "problem": _STR, "try": _STR},
    required=["keep", "problem", "try"],
)
_KEY_RESULT_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={"metric": _STR, "sbi": _SBI_SCHEMA, "kpt": _KPT_SCHEMA},
    required=["metric", "sbi", "kpt"],
)
RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={"key_results": types.Schema(type=types.Type.ARRAY, items=_KEY_RESULT_SCHEMA)},
    required=["key_results"],
)

# 一般的に知られている傾向（査読付き研究・公的機関のガイドライン等、確度の高い情報源のみを採用。
# 2026-07-15調査、2026-07-21に8学問分野の知見を追加・拡充。詳細な出典・不採用とした項目の理由は
# docs/setup-checklist.md 参照）。あくまで「傾向」の参考知識としてGeminiに渡すのみで、
# 判定ロジック(閾値等)には一切使わない。
# 実測: 分野ごとの知見を1〜2件のまま渡すだけだと、同じ状況(例:就寝時刻の遅れ)に対して
# 毎回「体内時計」等の最も典型的な1点に収束してしまい、日々似た説明の繰り返しになった。
# 分野ごとに複数の具体的な観点を持たせたうえで、_pick_disciplineによる日替わりの重点分野
# 指定と組み合わせることで、同じ状況でも日によって異なる角度の説明が出るようにしている。
REFERENCE_TENDENCIES = (
    "\n\n【参考知識：一般的に知られている傾向（複数の学問分野の一般的な知見を背景にした"
    "参考情報。断定的な基準や医療的な診断として扱わないこと。自然に触れられる場合のみ"
    "参考にし、無理にすべて盛り込む必要はない。同じ観点を毎回繰り返さず、"
    "当日の状況に最も関連する1〜2点を選んで多様な角度から述べること）】\n"
    "◆時間生物学（体内時計）\n"
    "- 概日リズムは光・食事・活動のタイミングによって同調するとされる\n"
    "- 就寝・起床時刻が日によって大きく変動すると、体内時計の乱れにつながりやすい傾向がある\n"
    "- 体内時計のズレは、体温やホルモン分泌のタイミングにも影響しうるとされる\n"
    "◆睡眠医学\n"
    "- 入眠までの時間は、平均的にはおよそ15分前後とされ、それより明らかに長い状態が続く場合は"
    "寝つきの困難さのサインとされる傾向がある\n"
    "- 睡眠効率（床上時間に対する実睡眠時間の割合）は睡眠の質を見る指標の一つとされる\n"
    "- 夜間の中途覚醒が多い状態が続くと、深い睡眠が妨げられやすいとされる\n"
    "◆ホメオスタシス（恒常性）\n"
    "- 睡眠には体内時計の要因に加え、起きている時間が長いほど眠気が高まる「睡眠圧」の"
    "要因があるとされ、不足が続くと「睡眠負債」として蓄積しうるという考え方がある\n"
    "- 自律神経は体温調節・消化・免疫など複数の調整機構に関わるとされる\n"
    "◆神経科学\n"
    "- 深い睡眠は記憶の整理や脳の疲労回復に関わるとされ、慢性的な睡眠不足は"
    "集中力や気分の安定に影響しうる傾向があるとされる\n"
    "- ストレスが続くと自律神経のバランスが乱れ、日中の集中力や気分の波として"
    "現れることがあるとされる\n"
    "◆運動生理学\n"
    "- 日中の適度な活動は夜間の睡眠の質に良い方向で関わりうるとされる一方、"
    "就寝直前の激しい運動は寝つきを妨げうるとされる傾向がある\n"
    "- 運動後の回復には、身体が休息モードへ切り替わる時間が必要とされる\n"
    "◆栄養学\n"
    "- 就寝直前の重い食事やカフェイン・アルコールの摂取は睡眠の質に影響しうるとされ、"
    "規則的な食事の時間帯は体内時計の同調にも関わるとされる\n"
    "- ストレスが続く状態では、特定の栄養素の消費が高まるとされることがある\n"
    "◆バイオメカニクス\n"
    "- 歩行など日常的な反復動作による活動量の確保は、身体活動の維持に資するとされる\n"
    "- 長時間同じ姿勢が続くことは、身体への負担蓄積につながりうるとされる\n"
    "◆行動心理学（不眠に対する認知行動療法・CBT-Iの考え方）\n"
    "- 就寝・起床時刻をなるべく一定に保つことや、寝床を睡眠以外の目的（仕事・スマートフォン等）"
    "に使わないことは、睡眠に関する行動面の工夫として一般的に知られている\n"
    "- ストレスや考え事で寝つきにくいときは、呼吸法などで心身を落ち着けることが"
    "一般的に勧められることがある\n"
    "◆ストレス・活動量の一般的傾向\n"
    "- 睡眠不足はストレスへの耐性を下げ、逆にストレスも睡眠の質に影響しうるという、"
    "互いに影響し合う関係にあるとされる\n"
    "- 1日の歩数は、成人でおよそ8,000歩程度が一つの目安とされることがある"
)

# 日替わりの重点分野の全候補（未知の指標名に対するフォールバック用）
_DISCIPLINES = [
    "時間生物学", "睡眠医学", "ホメオスタシス", "神経科学",
    "運動生理学", "栄養学", "バイオメカニクス", "行動心理学",
]

# 指標ごとに自然に結びつく分野だけに絞った候補（_pick_discipline参照）。
# 実測: 8分野を指標に関係なく均等にローテーションすると、「ストレス」に
# 「バイオメカニクス」が割り当たり「筋肉や関節への負担」という無理のある
# 説明になるケースがあった。指標と関連の薄い分野を除外し、こじつけを防ぐ
_METRIC_DISCIPLINES = {
    "歩数": ["運動生理学", "バイオメカニクス", "ホメオスタシス", "行動心理学"],
    "活動消費kcal": ["運動生理学", "バイオメカニクス", "栄養学", "ホメオスタシス"],
    "ストレス": ["ホメオスタシス", "神経科学", "行動心理学", "栄養学"],
    "総睡眠min": ["睡眠医学", "ホメオスタシス", "神経科学", "時間生物学"],
    "深睡眠min": ["睡眠医学", "神経科学", "ホメオスタシス"],
    "浅睡眠min": ["睡眠医学", "神経科学"],
    "REM_min": ["睡眠医学", "神経科学"],
    "入眠潜時min": ["睡眠医学", "行動心理学", "神経科学"],
    "睡眠効率": ["睡眠医学", "ホメオスタシス"],
    "就寝時刻": ["時間生物学", "行動心理学", "ホメオスタシス"],
    "起床時刻": ["時間生物学", "行動心理学", "ホメオスタシス"],
}


def _pick_discipline(date_str: str, metric: str) -> str:
    """日付+指標名から、状態を保存せずに一意な重点分野を1つ選ぶ。

    同じ被験者の同じ指標でも日付が変われば異なる分野になり、過去の生成履歴を
    保持しなくても「今日はどの角度で説明するか」を機械的に分散させられる
    （過去30日の生データは渡さない方針とは別軸。生成物の言い回しを分散させる
    ためのメタ情報であり、被験者データそのものではない）。候補は指標と関連の
    薄い分野を除いた_METRIC_DISCIPLINESから選び、未知の指標名は全分野から選ぶ。"""
    candidates = _METRIC_DISCIPLINES.get(metric, _DISCIPLINES)
    digest = hashlib.sha256(f"{date_str}|{metric}".encode("utf-8")).hexdigest()
    return candidates[int(digest, 16) % len(candidates)]

SYSTEM_PROMPT = (
    "あなたはフィットネス施設のトレーナー向けに、ゲスト（被験者）の日次コンディションデータから"
    "OKR＋SBI＋KPT形式のフィードバックレポートを作成するアシスタントです。"
    "与えられるのは、施策全体の目標(O)、睡眠（総睡眠時間・深い/浅い/REM睡眠・入眠潜時・睡眠効率・"
    "就寝/起床時刻）、ストレス、活動量（歩数・活動消費kcal）の実測値、"
    "本日KR（Key Result）として扱う指標の一覧（当日SD逸脱度が閾値を超えてフラグが立った指標）です。"
    "比較の軸は2つあります。"
    "(1) 施策開始前平均→施策開始後平均：施策全体を通じた長期的な変化。"
    "(2) 当日の値の、個人平均（原則は施策開始後平均。開始直後でデータが少ない間は開始前平均）"
    "からのSD逸脱度：直近の異常検知。"
    "加えて、欠測日数と、本人の前日アンケート回答（体調の自己評価・業務負荷の想定・食事の予定など）"
    "が与えられます。"
    "アンケートは前日に回答されたものです。設問文にある「今朝」「本日」はすべて前日を指すため、"
    "当日の予定として扱ってはいけません（例:「本日の業務負荷: 高い」は前日の業務負荷が高かったという意味。"
    "「夜に会食あり」はすでに終わった前日夜の会食）。"
    "前日の状況（業務負荷・会食・体調など）の影響や疲労が当日の数値に表れていないか、"
    "という視点で参考にしてください。"
    "\n\n"
    "本日KRとして与えられた指標それぞれについて、SBIとKPTの両方を作成してください。"
    "SBIは「事象の分析」（トレーナーが現状の裏付け・論理を理解するための客観的な記述）、"
    "KPTは「伝達するメッセージ」（トレーナーがそのままゲストへ声かけできる口語的な文章）と"
    "役割が異なります。両者は同じ内容を言い換えただけにならないようにしてください。"
    "具体的には、SBIのsituation/behaviorで述べた事実そのものをKPTのproblemで繰り返さない"
    "（KPTのproblemはゲスト向けにやわらげた言い方に変換すること）。"
    "SBIのimpact（データ・行動が目標(O)にどう影響するかの分析）と、"
    "KPTのtry（次回に向けた具体的な行動提案）も、分析と提案という別の役割を保つこと。"
    "- sbi.situation: 当日の数値・データから読み取れる客観的な事実\n"
    "- sbi.behavior: その背景にあると推測される、ゲストが取った具体的な行動"
    "（前日アンケート回答があれば優先的に参照する）\n"
    "- sbi.impact: その行動とデータが、目標(O)や今後のコンディションにどう影響するかの分析。"
    "下記の参考知識（時間生物学・神経科学・運動生理学・ホメオスタシス・栄養学・バイオメカニクス・"
    "睡眠医学・行動心理学）を、関連する場合のみ根拠として自然に使ってよい。"
    "ユーザープロンプトにKRごとの「重点分野」が指定されている場合は、他の観点を排除する必要はないが"
    "必ずその分野の視点にも触れること（同じ指標でも日によって異なる角度から説明するため）\n"
    "- kpt.keep: データから読み取れる、褒めるべき点・継続すべき点"
    "（そのKR自体に良い点が無ければ、他の指標や継続的な取り組みでもよい）\n"
    "- kpt.problem: 改善が必要な点。ゲストを責めないやわらかいトーンで\n"
    "- kpt.try: 明日以降に向けた、具体的で実行しやすい行動提案。"
    "参考知識にある行動面の工夫（就寝時刻を一定にする、就寝前の飲食・運動・スマートフォン使用を控える等）を"
    "関連する場合のみ提案に活かしてよい\n"
    "各項目は指定された文字数程度の自然な日本語1文で書いてください。"
    "アンケート回答がある日は、数値と自己申告のギャップ（本人は元気なつもりだが数値は低い等）にも着目してください。"
    "数値の羅列や絵文字は不要です。"
    "\n\n"
    "【安全に関する厳格な制約（最優先で守ること）】\n"
    "- 参考知識はあくまで一般的な傾向・知見であり、本人固有の医学的事実ではない。"
    "「〜です」「〜が原因です」のような断定は避け、「〜とされる傾向がある」"
    "「〜の可能性がある」等、一般論であることが分かる表現にとどめること。\n"
    "- いかなる病名・症状名（不眠症、うつ、自律神経失調症等）も挙げない。"
    "「〜の疑いがあります」「〜という状態です」等、医学的な診断や疾患を示唆する表現は"
    "絶対に使わないこと。\n"
    "- 治療・投薬・医療的介入を勧める表現（「〜を服用しましょう」「受診が必要です」等）は"
    "書かないこと。あくまで生活習慣上の一般的な工夫の提案にとどめる。\n"
    "- 深刻・継続的な不調が疑われるデータであっても、断定や診断はせず、"
    "「気になる状態が続く場合は専門家に相談することも一つの方法です」程度の一般的な"
    "案内にとどめ、それ以上踏み込まない。\n"
    "出力は指定されたJSON形式のみとし、前置き・説明文・Markdownのコードフェンスは一切含めないでください。"
    + REFERENCE_TENDENCIES
)


def build_client(settings: Settings) -> genai.Client:
    return genai.Client(vertexai=True, project=settings.gcp_project, location=settings.gcp_location)


def build_prompt(context: dict, objective_text: str, flagged_metrics: list[str], min_len: int, max_len: int) -> str:
    lines = [
        f"目標(O): {objective_text}",
        f"日付: {context['date']}",
        f"欠測日数（直近の空白日数）: {context['missing_days']}日",
        "（min系は分、就寝/起床時刻はHH:MM表記・差分は時間、睡眠効率は%）",
    ]

    trend_lines = []
    today_lines = []
    for metric, m in context["metrics"].items():
        value = m["value"]
        if pd.isna(value):
            continue
        unit = "h" if metric in TIME_METRICS else ""

        pre = m["pre_start_mean"]
        post = m["post_start_mean"]
        if pd.notna(pre) and pd.notna(post):
            trend_lines.append(
                f"- {metric}: 開始前平均={_fmt_value(metric, pre)} → 開始後平均={_fmt_value(metric, post)}"
                f"（{_fmt_delta(metric, pre, post, unit)}）"
            )

        flag = "【本日のKR対象】" if metric in flagged_metrics else ""
        sd_dev = _fmt(m["sd_dev"])
        basis = m.get("sd_basis") if isinstance(m.get("sd_basis"), str) else "開始後平均"
        today_lines.append(
            f"- {metric}: 当日={_fmt_value(metric, value)} {basis}からのSD逸脱度={sd_dev} {flag}"
        )

    if trend_lines:
        lines.append("\n【施策開始後の変化】(開始前平均→開始後平均。長期的な文脈として参考にする)")
        lines += trend_lines
    lines.append("\n【本日の状態】(個人平均からの逸脱)")
    lines += today_lines

    if context.get("form_answers"):
        lines.append("\n本人の前日アンケート回答（設問の「今朝」「本日」は前日を指す）:")
        for question, answer in context["form_answers"].items():
            lines.append(f"- {question}: {answer}")

    lines.append(f"\n本日KRとして扱う指標: {', '.join(flagged_metrics)}")

    if flagged_metrics:
        date_str = str(context["date"])
        hints = "\n".join(
            f"- {metric}: 「{_pick_discipline(date_str, metric)}」の観点を意識して触れる"
            for metric in flagged_metrics
        )
        lines.append(
            "\n【今回のKRごとの重点分野】(他の観点を排除する必要はないが、"
            f"必ずこれにも触れること。日によって異なる角度で説明するための指定)\n{hints}"
        )

    lines.append(
        f"\n上記の指標それぞれについて、SBI・KPT各項目を{min_len}〜{max_len}字程度の1文で作成し、"
        "次のJSON形式のみを出力してください（前置き・コードフェンス不要）:\n"
        '{"key_results": [{"metric": "<指標名。上記の指標名をそのまま使う>", '
        '"sbi": {"situation": "...", "behavior": "...", "impact": "..."}, '
        '"kpt": {"keep": "...", "problem": "...", "try": "..."}}]}'
    )
    return "\n".join(lines)


def _fmt_delta(metric: str, pre, post, unit: str) -> str:
    """開始前→開始後の変化量。睡眠効率は平均表示(%)に合わせてポイント表記にする
    （生値0-1のまま+.1f整形すると+4ptの変化も「+0.0」になってしまうため）。"""
    delta = post - pre
    if metric == "睡眠効率" and pre <= 1 and post <= 1:
        return f"{delta * 100:+.1f}pt"
    return f"{delta:+.1f}{unit}"


def _fmt_value(metric: str, v) -> str:
    """指標ごとに人間が読める形へ整形する（時刻はHH:MM、睡眠効率は%、総睡眠は時間併記）。"""
    if metric in TIME_METRICS:
        total_min = round(float(v) % 24 * 60)
        return f"{total_min // 60}:{total_min % 60:02d}"
    if metric == "睡眠効率" and isinstance(v, (int, float)) and v <= 1:
        return f"{float(v) * 100:.0f}%"
    if metric == TOTAL_SLEEP_COLUMN:
        return f"{float(v):.0f}分({float(v) / 60:.1f}時間)"
    return str(v)


def _fmt(v) -> str:
    if pd.isna(v):
        return "N/A"
    return f"{v:+.1f}" if isinstance(v, (int, float)) else str(v)


def format_feedback(objective_text: str, key_results: list[dict]) -> str:
    """OKR＋SBI＋KPTの構造をログシートの「コメント」セル用テキストに整形する。"""
    lines = [f"【O】{objective_text}"]
    if not key_results:
        lines.append(NO_FLAG_COMMENT)
        return "\n".join(lines)

    for kr in key_results:
        metric = kr.get("metric") or "?"
        sbi = kr.get("sbi") or {}
        kpt = kr.get("kpt") or {}
        lines.append(f"\n【KR: {metric}】")
        lines.append("[トレーナー分析]")
        lines.append(f"S: {sbi.get('situation', '')}")
        lines.append(f"B: {sbi.get('behavior', '')}")
        lines.append(f"I: {sbi.get('impact', '')}")
        lines.append("[ゲストへの伝え方]")
        lines.append(f"K: {kpt.get('keep', '')}")
        lines.append(f"P: {kpt.get('problem', '')}")
        lines.append(f"T: {kpt.get('try', '')}")
    return "\n".join(lines)


def generate_comment(
    client: genai.Client,
    model: str,
    context: dict,
    objective_text: str,
    min_len: int,
    max_len: int,
) -> str:
    flagged_metrics = [
        metric for metric, m in context["metrics"].items() if m.get("flagged") and pd.notna(m.get("value"))
    ]
    if not flagged_metrics:
        return format_feedback(objective_text, [])

    prompt = build_prompt(context, objective_text, flagged_metrics, min_len, max_len)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=3000,
            # gemini-2.5-flashは既定で内部思考(thinking)を行い、その思考トークンも
            # max_output_tokensの予算に含まれる。このタスクは深い推論は不要なため無効化する
            # (有効のままだと本文生成前に予算切れで途中で打ち切られることがある)
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )
    raw = (response.text or "").strip()
    try:
        data = json.loads(raw)
        key_results = data.get("key_results", [])
        if not isinstance(key_results, list):
            raise ValueError("key_resultsが配列ではありません")
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        # JSON生成に失敗した場合でもジョブ全体を落とさず、KR無しとして扱う
        # （翌日以降、データハッシュ不一致により自動的に再生成が試みられる）
        logger.warning("Gemini応答のJSON解析に失敗しました: %s / raw=%s", e, raw)
        key_results = []

    sane_key_results = []
    for kr in key_results:
        if _is_sane_key_result(kr):
            sane_key_results.append(kr)
        else:
            logger.warning("KRの出力が異常に長く出力崩れとみなして破棄します: metric=%s", kr.get("metric"))

    return format_feedback(objective_text, sane_key_results)


# response_schemaはJSONの構造(キーの階層)は強制するが、文字列フィールドの中身までは
# 検証しない。実測: response_schema指定下でもGeminiが「前置きなしでJSONのみ出力」の指示を
# 一瞬破り、自己言及・謝罪・出力のやり直しを1つの文字列フィールドの中に書き連ねてしまう
# ケースがあった(JSON構文としては妥当なため例外にならず、そのままシートに書き込まれてしまう)。
# 各項目は本来指定字数(〜120字程度)に収まるはずなので、明らかに逸脱した長さのKRは
# 出力崩れとみなして破棄する
_SANE_FIELD_MAX_LEN = 200


def _is_sane_key_result(kr: dict) -> bool:
    sbi = kr.get("sbi") or {}
    kpt = kr.get("kpt") or {}
    fields = [
        sbi.get("situation"), sbi.get("behavior"), sbi.get("impact"),
        kpt.get("keep"), kpt.get("problem"), kpt.get("try"),
    ]
    return all(isinstance(f, str) and len(f) <= _SANE_FIELD_MAX_LEN for f in fields)
