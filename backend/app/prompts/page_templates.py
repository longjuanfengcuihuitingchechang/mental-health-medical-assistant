from __future__ import annotations

from app.schemas.page_assistant import AgeGroup, PatientPage


PAGE_GUIDE = {
    PatientPage.OVERVIEW: ("心理健康概览", "查看情绪打卡、最近筛查、趋势和待办随访"),
    PatientPage.SUPPORT: ("智能支持", "了解助手边界、进行当前页问答和查找支持资源"),
    PatientPage.ASSESSMENTS: ("心理测评", "查看可用量表、继续测评和了解非诊断性结果"),
    PatientPage.WELLBEING: ("情绪日记", "记录情绪、压力、睡眠并查看个人趋势"),
    PatientPage.RESOURCES: ("随访与资源", "查看随访任务、专业帮助资源和隐私设置"),
    PatientPage.CARE: ("患者诊疗", "根据真实医生状态、既往接诊关系和排队情况选择医生"),
}

FEATURE_CAPABILITIES = {
    PatientPage.OVERVIEW: {
        "page": "浏览个人心理健康概览",
        "mood_checkin": "完成今日情绪打卡",
        "latest_screening": "查看最近一次筛查摘要",
        "trend": "查看近期个人趋势",
        "followups": "查看待办随访",
        "crisis_resources": "打开现实求助资源",
    },
    PatientPage.SUPPORT: {
        "page": "了解智能支持页面",
        "ask_question": "询问当前页功能",
        "formal_care": "进入正式诊疗导航",
    },
    PatientPage.ASSESSMENTS: {
        "page": "浏览心理测评页面",
        "available_scales": "查看已发布量表",
        "continue_assessment": "继续未完成测评",
        "results": "查看非诊断性测评结果",
    },
    PatientPage.WELLBEING: {
        "page": "浏览情绪日记页面",
        "new_entry": "新增情绪日记",
        "history": "查看历史记录",
        "trend": "查看情绪与睡眠趋势",
    },
    PatientPage.RESOURCES: {
        "page": "浏览随访与资源页面",
        "followups": "查看随访任务",
        "professional_help": "查看专业帮助资源",
        "privacy": "查看隐私与 AI 同意设置",
    },
    PatientPage.CARE: {
        "page": "浏览患者诊疗导航",
        "doctor_selection": "选择可接诊医生",
        "previous_doctor": "查看原接诊医生",
        "queue_status": "查看真实排队和医生返岗状态",
    },
}


def _intro(page: PatientPage, feature_key: str) -> str:
    title = PAGE_GUIDE[page][0]
    capability = FEATURE_CAPABILITIES[page][feature_key]
    suffix = "。如需正式心理诊疗，请告诉我“我要就诊”。"
    return f"这里是“{title}”中的“{capability}”功能。我可以说明它的用途和操作方法{suffix}"


INTRO_TEMPLATES = {
    (page, feature): _intro(page, feature)
    for page, features in FEATURE_CAPABILITIES.items()
    for feature in features
}


def build_page_system_prompt(
    page: PatientPage,
    feature_key: str,
    age_group: AgeGroup,
) -> str:
    title = PAGE_GUIDE[page][0]
    capability = FEATURE_CAPABILITIES[page][feature_key]
    tone = {
        AgeGroup.CHILD: "使用适龄、尊重、非命令式语言，不幼稚化。",
        AgeGroup.ADULT: "使用礼貌、清晰、简短的语言。",
        AgeGroup.OLDER_ADULT: "使用尊重、清晰、不催促且不居高临下的语言。",
    }[age_group]
    return (
        f"你是患者端“{title}”页面“{capability}”功能的助手。"
        "只回答当前功能的用途和操作，不回答其他页面内容。"
        "不得诊断、开药、替代医生、编造医生状态或声称已经联系任何人。"
        "如果信息不足，要明确说不知道。回答不超过160个汉字。"
        f"{tone}"
    )
