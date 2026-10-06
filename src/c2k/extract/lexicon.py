"""Domain lexicon used by the MockLLM and by a few deterministic rules.

In the production project the topic whitelist, the sensitive-topic set
(forces ``escalation_flag=true``) and the keyword hints lived in worker
memory files. Here they are plain data for a neutral coworking-support domain.
Swap this module to retarget the mock to another domain.
"""
from __future__ import annotations

import re

TOPIC_WHITELIST = [
    "wifi_access", "printer_issue", "meeting_room_booking", "access_card",
    "invoice_billing", "locker_request", "parking", "membership_change",
    "mail_package", "coffee_machine", "guest_pass", "ac_temperature", "other",
]

# Topics where the agent is the authority (account/money/state change):
# the KB answer can never be final, the request must go to a human.
SENSITIVE_TOPICS = {"access_card", "invoice_billing", "locker_request", "membership_change", "mail_package"}

# keyword -> topic (multilingual, lowercase substrings)
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "wifi_access": ["wifi", "wi-fi", "internet", "\u0438\u043d\u0442\u0435\u0440\u043d\u0435\u0442", "ไวไฟ", "อินเทอร์เน็ต", "network", "\u0441\u0435\u0442\u044c"],
    "printer_issue": ["printer", "print", "\u043f\u0440\u0438\u043d\u0442\u0435\u0440", "\u043f\u0435\u0447\u0430\u0442", "เครื่องพิมพ์", "พิมพ์", "paper jam"],
    "meeting_room_booking": ["meeting room", "room b", "room d", "book", "\u043f\u0435\u0440\u0435\u0433\u043e\u0432\u043e\u0440", "\u0431\u0440\u043e\u043d", "ห้องประชุม", "จอง", "booked"],
    "access_card": ["access card", "card", "\u043a\u0430\u0440\u0442", "door", "\u0434\u0432\u0435\u0440\u044c", "บัตร", "ประตู", "reader", "\u0441\u0447\u0438\u0442\u044b\u0432\u0430\u0442\u0435\u043b\u044c"],
    "invoice_billing": ["invoice", "fee", "charged", "\u0441\u0447\u0451\u0442", "\u0441\u0447\u0435\u0442", "\u0430\u0431\u043e\u043d\u043f\u043b\u0430\u0442", "\u0441\u043f\u0438\u0441\u044b\u0432\u0430", "ใบแจ้งหนี้", "ค่าสมาชิก", "ตัด"],
    "locker_request": ["locker", "\u0448\u043a\u0430\u0444\u0447\u0438\u043a", "ล็อกเกอร์"],
    "parking": ["parking", "\u043f\u0430\u0440\u043a\u043e\u0432", "ที่จอดรถ", "จอดรถ"],
    "membership_change": ["hot desk", "dedicated desk", "plan", "\u0442\u0430\u0440\u0438\u0444", "\u0437\u0430\u043a\u0440\u0435\u043f\u043b\u0451\u043d\u043d\u044b\u0439 \u0441\u0442\u043e\u043b", "แพ็กเกจ", "โต๊ะประจำ"],
    "mail_package": ["package", "parcel", "\u043f\u043e\u0441\u044b\u043b\u043a", "\u043f\u0430\u043a\u0435\u0442", "พัสดุ", "tracking", "\u0442\u0440\u0435\u043a\u0438\u043d\u0433"],
    "coffee_machine": ["coffee", "\u043a\u043e\u0444\u0435", "กาแฟ", "brew"],
    "guest_pass": ["guest pass", "visitor", "\u0433\u043e\u0441\u0442\u0435\u0432", "\u043f\u043e\u0441\u0435\u0442\u0438\u0442\u0435\u043b", "บัตรแขก", "ผู้มาเยี่ยม", "แขก"],
    "ac_temperature": ["freezing", "cold", "ac ", "air con", "\u0445\u043e\u043b\u043e\u0434\u043d\u043e", "\u043a\u043e\u043d\u0434\u0438\u0446\u0438\u043e\u043d\u0435\u0440", "หนาว", "แอร์"],
}

# sub-intent detection -> English canonical case template (what the mock "writes")
INTENTS: list[tuple[str, str, list[str], str]] = [
    ("wifi_access", "cannot_connect", ["drop", "not working", "no internet", "\u043e\u0442\u0432\u0430\u043b\u0438\u0432\u0430", "\u043d\u0435 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442", "\u043d\u0435\u0442 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f", "หลุด", "ใช้ไม่ได้"],
     "A member reports that the office wifi is unstable or not connecting at their desk or floor and asks for a fix."),
    ("wifi_access", "guest_password", ["password", "\u043f\u0430\u0440\u043e\u043b\u044c", "รหัส"],
     "A member asks for the guest wifi credentials for a visiting client."),
    ("printer_issue", "print_job_stuck", ["jam", "queued", "\u0437\u0430\u043c\u044f\u0442", "\u0432\u0438\u0441\u0438\u0442", "ติด", "ค้าง"],
     "A member reports that a shared printer shows a paper-jam error with no visible jam and their job is stuck in the queue."),
    ("meeting_room_booking", "booking_conflict", ["someone else", "booked it too", "\u0443\u0436\u0435 \u0441\u0438\u0434\u044f\u0442", "\u0442\u043e\u0436\u0435 \u0437\u0430\u0431\u0440\u043e\u043d\u0438\u0440", "จองเหมือนกัน"],
     "A member finds their booked meeting room occupied by another member claiming the same slot."),
    ("meeting_room_booking", "how_to_book", ["how do i book", "\u043a\u0430\u043a \u0437\u0430\u0431\u0440\u043e\u043d\u0438\u0440\u043e\u0432\u0430\u0442\u044c", "จองห้องประชุม", "find the button", "\u043a\u043d\u043e\u043f\u043a\u0443", "ปุ่ม"],
     "A member asks how to book a meeting room in the member app."),
    ("access_card", "card_lost", ["lost", "\u043f\u043e\u0442\u0435\u0440\u044f\u043b", "\u0445\u0430\u0439", "หาย", "block", "\u0437\u0430\u0431\u043b\u043e\u043a", "ระงับ"],
     "A member lost their access card and asks to block it and issue a replacement."),
    ("access_card", "card_not_working", ["doesn't open", "\u043d\u0435 \u043e\u0442\u043a\u0440\u044b\u0432\u0430\u0435\u0442", "เปิดประตูไม่ได้", "blinks", "\u043c\u0438\u0433\u0430\u0435\u0442", "กะพริบ"],
     "A member's access card does not open the door outside daytime hours."),
    ("invoice_billing", "invoice_wrong_amount", ["shows", "cheaper", "\u0434\u0435\u0448\u0435\u0432\u043b\u0435", "ถูกกว่า", "wrong", "\u043d\u0435\u043f\u0440\u0430\u0432\u0438\u043b\u044c"],
     "A member believes last month's invoice is higher than their plan and asks for a check."),
    ("invoice_billing", "payment_date", ["when", "\u043a\u0430\u043a\u043e\u0433\u043e \u0447\u0438\u0441\u043b\u0430", "วันไหน", "charged", "\u0441\u043f\u0438\u0441\u044b\u0432\u0430", "ตัด"],
     "A member asks on which day the monthly membership fee is charged."),
    ("locker_request", "need_locker", ["locker", "\u0448\u043a\u0430\u0444\u0447\u0438\u043a", "ล็อกเกอร์"],
     "A member asks to be assigned a locker to store equipment near their desk."),
    ("parking", "parking_availability", ["parking", "\u043f\u0430\u0440\u043a\u043e\u0432", "จอดรถ"],
     "A member asks whether member parking is available and how to use it."),
    ("membership_change", "upgrade_plan", ["dedicated", "\u0437\u0430\u043a\u0440\u0435\u043f\u043b\u0451\u043d\u043d\u044b\u0439", "โต๊ะประจำ", "move from", "\u043f\u0435\u0440\u0435\u0439\u0442\u0438", "เปลี่ยนจาก"],
     "A member wants to change their plan from hot desk to a dedicated desk from a given date."),
    ("mail_package", "package_arrived", ["package", "\u043f\u043e\u0441\u044b\u043b\u043a", "พัสดุ"],
     "A member asks whether a package addressed to them has been delivered to the space."),
    ("coffee_machine", "machine_error", ["error", "\u043e\u0448\u0438\u0431\u043a", "error e", "won't brew", "\u043d\u0435 \u0432\u0430\u0440\u0438\u0442", "ไม่ชง"],
     "A member reports that a shared coffee machine shows an error code and does not brew."),
    ("guest_pass", "register_guest", ["guest", "\u0433\u043e\u0441\u0442\u0435\u0432", "แขก", "visitor", "\u043f\u043e\u0441\u0435\u0442\u0438\u0442\u0435\u043b"],
     "A member asks how to arrange a day pass for a visiting guest."),
    ("ac_temperature", "too_cold", ["freezing", "cold", "\u0445\u043e\u043b\u043e\u0434\u043d\u043e", "หนาว", "ac", "\u043a\u043e\u043d\u0434\u0438\u0446\u0438\u043e\u043d\u0435\u0440", "แอร์"],
     "A member complains that the open space is too cold and asks to adjust the air conditioning."),
]

# chains used by the mock LEADS_TO judge: (topic, intent_a) -> intent_b
LEADS_TO_HINTS = {
    ("access_card", "card_not_working"): "upgrade_plan",
    ("wifi_access", "guest_password"): "register_guest",
    ("meeting_room_booking", "how_to_book"): "booking_conflict",
}

HOLDING_ACK_RE = re.compile(
    r"^(let me check|checking|on it|i'?ll (look|ask)|hold on|\u0441\u0435\u0439\u0447\u0430\u0441 \u0443\u0442\u043e\u0447\u043d\u044e|\u0438\u0434\u0443 \u0441\u043c\u043e\u0442\u0440\u0435\u0442\u044c|\u0441\u043c\u043e\u0442\u0440\u044e|\u043f\u043e\u0441\u043c\u043e\u0442\u0440\u044e|\u0441\u043f\u0440\u043e\u0448\u0443|\u043f\u0440\u043e\u0432\u0435\u0440\u044f\u044e|"
    r"ขอเช็ก|กำลังไปดู|ขอตรวจสอบ|ขอถาม|ขอดู|blocking it now|\u0431\u043b\u043e\u043a\u0438\u0440\u0443\u044e|ระงับให้เลย|good news|\u043e\u0442\u043b\u0438\u0447\u043d\u043e|ดีเลย)",
    re.IGNORECASE,
)
ESCALATION_RE = re.compile(r"(forward|escalat|\u043f\u0435\u0440\u0435\u0434\u0430\u043c|ส่งเรื่อง|ส่งต่อ|asked billing|\u043f\u043e\u043f\u0440\u043e\u0441\u0438\u043b \u0431\u0438\u043b\u043b\u0438\u043d\u0433|แจ้งฝ่ายบิลลิ่ง)", re.IGNORECASE)
REMINDER_RE = re.compile(r"(don'?t\s+forget|\u043d\u0435 \u0437\u0430\u0431\u0443\u0434\u044c|อย่าลืม|please\s+remember|reminder)", re.IGNORECASE)
MID_THREAD_RE = re.compile(r"^(yes|ok|\u0434\u0430|\u043f\u043e\u043d\u044f\u043b|เข้าใจ)[^.!?]{0,25}?(\bbut\b|\b\u043d\u043e\b|แต่)", re.IGNORECASE)
COMPLIANCE_RE = re.compile(r"^(sent|done|already sent|\u043e\u0442\u043f\u0440\u0430\u0432\u0438\u043b[\u0430]?|\u0433\u043e\u0442\u043e\u0432\u043e|ส่งแล้ว|เรียบร้อย)", re.IGNORECASE)


def guess_topic(text: str) -> str:
    t = (text or "").lower()
    best, best_n = "other", 0
    for topic, kws in TOPIC_KEYWORDS.items():
        n = sum(1 for k in kws if k in t)
        if n > best_n:
            best, best_n = topic, n
    return best


def guess_intent(topic: str, text: str) -> tuple[str, str]:
    t = (text or "").lower()
    for tp, intent, kws, template in INTENTS:
        if tp == topic and any(k in t for k in kws):
            return intent, template
    for tp, intent, kws, template in INTENTS:
        if tp == topic:
            return intent, template
    return "general", f"A member raises a request related to {topic.replace('_', ' ')}."
