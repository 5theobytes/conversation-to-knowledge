"""Generate a reproducible synthetic corpus of coworking member-support chats.

Domain: a coworking space's member support channel. Members (requesters)
write in English or Thai; support staff (agents) answer. Every name,
number and situation is invented. The generator is seeded, so the output is
byte-identical across runs.

Usage:
    python scripts/make_synthetic.py [--out demo_data/synthetic_messages.jsonl] [--seed 7] [--n 40]

Each line of the output is one message::

    {"chat_id", "msg_id", "ts", "from_id", "from_role", "text", "reply_to"}

The corpus deliberately contains:
  * real requests with a resolution (the KB signal),
  * requests that stay unresolved or get escalated,
  * noise: greeting-only threads, agent-initiated broadcasts with member
    compliance, reminders, mid-thread replies (all must be dropped),
  * raw "volatile" values (phone numbers, card numbers, amounts, dates,
    e-mails) that the pipeline must scrub into <placeholders>,
  * one 3-party group chat with interleaved senders (session dyad-rule demo).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "demo_data" / "synthetic_messages.jsonl"

MEMBERS = [
    ("m-01", "Mira Okonkwo", "en"), ("m-02", "Dariusz Lind", "en"),
    ("m-03", "Ananya Pillai", "en"), ("m-04", "Tomas Vega", "en"),
    ("m-05", "Zhanna Kirilenko", "en"), ("m-06", "Rustam Aliyev", "en"),
    ("m-07", "Vera Tsoi", "en"), ("m-08", "Niran Chaiya", "th"),
    ("m-09", "Pimchan Suwan", "th"), ("m-10", "Kiet Boonmee", "th"),
]
AGENTS = [("a-01", "Sasha"), ("a-02", "Lek")]

# ---------------------------------------------------------------------------
# Scenario templates. {name} = member first name, other braces = volatile values.
# Each scenario: topic, sub-intent, per-language requester opening(s), agent
# holding ack (optional), agent resolution(s) per language, outcome.
# ---------------------------------------------------------------------------
SCENARIOS: list[dict] = [
    {
        "topic": "wifi_access", "intent": "cannot_connect",
        "ask": {
            "en": ["Hi, the wifi on the 3rd floor keeps dropping, I can't join my call. Any fix?",
                   "Hello, wifi not working at desk {desk}, my laptop says no internet"],
            
            "th": ["สวัสดีค่ะ wifi ชั้น 3 หลุดตลอดเลย เข้าประชุมไม่ได้ ช่วยดูให้หน่อยได้ไหมคะ",
                   "สวัสดีครับ ไวไฟที่โต๊ะ {desk} ใช้ไม่ได้ครับ โน้ตบุ๊กขึ้นว่าไม่มีอินเทอร์เน็ต"],
        },
        "hold": {"en": "Let me check with the network team.",  "th": "ขอเช็กกับทีมเน็ตเวิร์กก่อนนะคะ"},
        "resolve": {
            "en": "Please forget the network and reconnect to the 5GHz one named 'Hub-5G', the 2.4GHz one is congested on that floor. If it still drops, switch to the ethernet port under the desk.",
            
            "th": "รบกวนลบเครือข่ายแล้วเชื่อมต่อใหม่กับ 5GHz ชื่อ 'Hub-5G' นะคะ 2.4GHz ชั้นนั้นคนใช้เยอะ ถ้ายังหลุดอยู่ให้เสียบสาย LAN ใต้โต๊ะได้เลยค่ะ",
        },
        "outcome": "resolved",
    },
    {
        "topic": "wifi_access", "intent": "guest_password",
        "ask": {
            "en": ["What's the guest wifi password? I have a client coming at {time}."],
            
            "th": ["ขอรหัส wifi สำหรับแขกหน่อยค่ะ มีลูกค้ามาตอน {time}"],
        },
        "hold": None,
        "resolve": {
            "en": "The guest network is 'Hub-Guest'; the password rotates weekly and is printed on the reception screen. Your guest can also scan the QR code at the front desk.",
            
            "th": "เครือข่ายแขกชื่อ 'Hub-Guest' ค่ะ รหัสเปลี่ยนทุกสัปดาห์และแสดงบนจอที่แผนกต้อนรับ แขกสแกน QR ที่หน้าเคาน์เตอร์ได้เลยค่ะ",
        },
        "outcome": "informational",
    },
    {
        "topic": "printer_issue", "intent": "print_job_stuck",
        "ask": {
            "en": ["The printer near the kitchen says 'paper jam' but there's no paper stuck. My job is queued since {time}."],
            
            "th": ["เครื่องพิมพ์ข้างครัวขึ้นว่ากระดาษติด แต่ไม่มีกระดาษติดเลยค่ะ งานค้างตั้งแต่ {time}"],
        },
        "hold": {"en": "On it.",  "th": "กำลังไปดูค่ะ"},
        "resolve": {
            "en": "Cleared it: the rear tray sensor was stuck. Your job printed. Next time, open the rear door once and close it; that resets the sensor.",
            
            "th": "แก้ให้แล้วค่ะ เซ็นเซอร์ถาดหลังค้าง งานพิมพ์ออกแล้วนะคะ ครั้งหน้าเปิดฝาหลังแล้วปิดหนึ่งครั้ง เซ็นเซอร์จะรีเซ็ตค่ะ",
        },
        "outcome": "resolved",
    },
    {
        "topic": "meeting_room_booking", "intent": "booking_conflict",
        "ask": {
            "en": ["I booked room B for {time} but someone else is inside and says they booked it too. Can you check?"],
            
            "th": ["จองห้อง B ไว้ตอน {time} แต่มีคนอยู่ข้างในบอกว่าจองเหมือนกัน ช่วยเช็กให้หน่อยได้ไหมครับ"],
        },
        "hold": {"en": "Checking the calendar now.",  "th": "ขอเช็กปฏิทินแป๊บนะคะ"},
        "resolve": {
            "en": "There was a double booking from the old calendar sync. I moved your slot to room D at the same time and cancelled the duplicate. Please re-check the app.",
            
            "th": "มีการจองซ้ำจากปฏิทินเก่าค่ะ ย้ายของคุณไปห้อง D เวลาเดิมและยกเลิกอันซ้ำแล้ว รบกวนเช็กในแอปอีกครั้งนะคะ",
        },
        "outcome": "resolved",
    },
    {
        "topic": "meeting_room_booking", "intent": "how_to_book",
        "ask": {
            "en": ["How do I book a meeting room for tomorrow? Can't find the button in the app."],
            
            "th": ["จองห้องประชุมสำหรับพรุ่งนี้ยังไงคะ หาปุ่มในแอปไม่เจอเลย"],
        },
        "hold": None,
        "resolve": {
            "en": "In the member app go to Spaces > Rooms, pick the date, then tap the room's time grid. Bookings up to 2 hours per day are included in your plan.",
            
            "th": "ในแอปสมาชิกไปที่ Spaces > Rooms เลือกวันแล้วแตะตารางเวลาของห้องค่ะ จองได้ไม่เกิน 2 ชั่วโมงต่อวันรวมในแพ็กเกจแล้วค่ะ",
        },
        "outcome": "informational",
    },
    {
        "topic": "access_card", "intent": "card_lost",
        "ask": {
            "en": ["I lost my access card somewhere yesterday, card number {card}. Can you block it and issue a new one?"],
            
            "th": ["บัตรเข้าออกหายเมื่อวานค่ะ เลขบัตร {card} ช่วยระงับแล้วออกใบใหม่ให้หน่อยได้ไหมคะ"],
        },
        "hold": {"en": "Blocking it now.",  "th": "ระงับให้เลยค่ะ"},
        "resolve": {
            "en": "Old card is blocked. A replacement is ready at reception, bring your ID; the replacement fee of {amount} will be added to your next invoice.",
            
            "th": "ระงับบัตรเก่าแล้วค่ะ บัตรใหม่รับได้ที่แผนกต้อนรับ นำบัตรประชาชนมาด้วยนะคะ ค่าออกบัตรใหม่ {amount} จะรวมในใบแจ้งหนี้รอบหน้าค่ะ",
        },
        "outcome": "resolved",
    },
    {
        "topic": "access_card", "intent": "card_not_working",
        "ask": {
            "en": ["My card doesn't open the door after {time}, the reader just blinks red."],
            
            "th": ["บัตรเปิดประตูไม่ได้หลัง {time} ค่ะ เครื่องอ่านกะพริบสีแดงอย่างเดียว"],
        },
        "hold": None,
        "resolve": {
            "en": "Your plan has day-access only (08:00-20:00). Evening access needs the 24/7 add-on; reply here if you'd like it switched on and I'll forward the request to billing.",
            
            "th": "แพ็กเกจของคุณเข้าได้เฉพาะกลางวัน (08:00-20:00) ค่ะ ถ้าต้องการเข้าตอนเย็นต้องเพิ่มออปชัน 24/7 แจ้งมาได้เลย เดี๋ยวส่งเรื่องให้ฝ่ายบิลลิ่งค่ะ",
        },
        "outcome": "escalated",
    },
    {
        "topic": "invoice_billing", "intent": "invoice_wrong_amount",
        "ask": {
            "en": ["My invoice for last month shows {amount} but my plan is cheaper. Can someone check? My email is {email}"],
            
            "th": ["ใบแจ้งหนี้เดือนที่แล้วขึ้น {amount} แต่แพ็กเกจของฉันถูกกว่านี้ค่ะ ช่วยเช็กให้หน่อย อีเมล {email}"],
        },
        "hold": {"en": "I'll look into it.",  "th": "ขอตรวจสอบก่อนนะคะ"},
        "resolve": {
            "en": "Found it: two meeting-room overages were billed at the non-member rate. I've asked billing to reissue the invoice; you'll get the corrected one by email within 2 working days.",
            
            "th": "เจอแล้วค่ะ ค่าห้องประชุมเกิน 2 ครั้งถูกคิดในราคาที่ไม่ใช่สมาชิก แจ้งฝ่ายบิลลิ่งออกใบใหม่แล้ว จะได้รับทางอีเมลภายใน 2 วันทำการค่ะ",
        },
        "outcome": "resolved",
    },
    {
        "topic": "invoice_billing", "intent": "payment_date",
        "ask": {
            "en": ["When is the monthly fee charged? I want to make sure the card has funds."],
            
            "th": ["ค่าสมาชิกรายเดือนตัดวันไหนคะ อยากให้มั่นใจว่ามีเงินในบัตร"],
        },
        "hold": None,
        "resolve": {
            "en": "Fees are charged on the 1st of each month; if it fails we retry on the 3rd and send a reminder email.",
            
            "th": "ตัดค่าบริการทุกวันที่ 1 ของเดือนค่ะ ถ้าไม่ผ่านจะลองอีกครั้งวันที่ 3 และส่งอีเมลเตือนค่ะ",
        },
        "outcome": "informational",
    },
    {
        "topic": "locker_request", "intent": "need_locker",
        "ask": {
            "en": ["Can I get a locker? I keep a monitor here and don't want to carry it. Desk {desk}."],
            
            "th": ["ขอล็อกเกอร์ได้ไหมคะ มีจอมอนิเตอร์ไว้ที่นี่ ไม่อยากหิ้วไปมา โต๊ะ {desk} ค่ะ"],
        },
        "hold": {"en": "Let me see what's free.",  "th": "ขอดูว่าว่างตู้ไหนนะคะ"},
        "resolve": {
            "en": "Assigned you locker L-{locker} next to your desk. Set your own 4-digit code on the keypad; the locker add-on costs {amount} per month and starts on your next invoice.",
            
            "th": "จัดล็อกเกอร์ L-{locker} ข้างโต๊ะให้แล้วค่ะ ตั้งรหัส 4 หลักเองที่แป้นได้เลย ค่าล็อกเกอร์ {amount} ต่อเดือน เริ่มคิดในใบแจ้งหนี้รอบหน้าค่ะ",
        },
        "outcome": "resolved",
    },
    {
        "topic": "parking", "intent": "parking_availability",
        "ask": {
            "en": ["Is there member parking? I'll drive in on {date}."],
            
            "th": ["มีที่จอดรถสำหรับสมาชิกไหมคะ จะขับรถมาวันที่ {date}"],
        },
        "hold": None,
        "resolve": {
            "en": "Yes: level -1 of the building, 6 member spots, first come first served. Validate your ticket at reception to get the member rate.",
            
            "th": "มีค่ะ ชั้น -1 ของอาคาร มี 6 ช่องสำหรับสมาชิก มาก่อนได้ก่อน เอาบัตรจอดมาประทับที่แผนกต้อนรับเพื่อรับราคาสมาชิกนะคะ",
        },
        "outcome": "informational",
    },
    {
        "topic": "membership_change", "intent": "upgrade_plan",
        "ask": {
            "en": ["I'd like to move from hot desk to a dedicated desk from {date}. What do I need to do?"],
            
            "th": ["อยากเปลี่ยนจาก hot desk เป็นโต๊ะประจำตั้งแต่ {date} ค่ะ ต้องทำยังไงบ้างคะ"],
        },
        "hold": {"en": "Good news, let me check availability.",  "th": "ดีเลยค่ะ ขอเช็กโต๊ะว่างก่อนนะคะ"},
        "resolve": {
            "en": "Desk {desk} by the window is free from that date. I've sent the plan-change form to your email; sign it and the new rate applies from the next billing cycle.",
            
            "th": "โต๊ะ {desk} ริมหน้าต่างว่างตั้งแต่วันนั้นค่ะ ส่งแบบฟอร์มเปลี่ยนแพ็กเกจไปที่อีเมลแล้ว เซ็นกลับมา ราคาใหม่จะเริ่มรอบบิลถัดไปค่ะ",
        },
        "outcome": "resolved",
    },
    {
        "topic": "mail_package", "intent": "package_arrived",
        "ask": {
            "en": ["Did a package arrive for me today? Tracking says delivered at {time}."],
            
            "th": ["วันนี้มีพัสดุมาถึงฉันไหมคะ ระบบติดตามบอกว่าส่งแล้วตอน {time}"],
        },
        "hold": {"en": "Checking the mailroom.",  "th": "ขอเช็กห้องพัสดุนะคะ"},
        "resolve": {
            "en": "Yes, it's in the mailroom shelf under your name. Pick it up at reception with your card; we hold packages for 5 days.",
            
            "th": "มีค่ะ อยู่ในห้องพัสดุบนชั้นที่มีชื่อคุณ รับได้ที่แผนกต้อนรับโดยใช้บัตร เก็บพัสดุไว้ให้ 5 วันค่ะ",
        },
        "outcome": "resolved",
    },
    {
        "topic": "coffee_machine", "intent": "machine_error",
        "ask": {
            "en": ["Coffee machine on floor 2 shows error E{code} and won't brew."],
            
            "th": ["เครื่องชงกาแฟชั้น 2 ขึ้น error E{code} แล้วไม่ชงค่ะ"],
        },
        "hold": None,
        "resolve": {
            "en": "That code means the drip tray is full. Pull the tray out, empty it, push it back until it clicks. If it repeats, use the machine on floor 1 and we'll call the technician.",
            
            "th": "โค้ดนี้แปลว่าถาดรองน้ำเต็มค่ะ ดึงถาดออก เทน้ำทิ้ง แล้วดันกลับจนดังคลิก ถ้าขึ้นอีกใช้เครื่องชั้น 1 ก่อน เดี๋ยวเรียกช่างค่ะ",
        },
        "outcome": "informational",
    },
    {
        "topic": "guest_pass", "intent": "register_guest",
        "ask": {
            "en": ["I need a guest pass for a visitor on {date}, her name is {guest}. How does it work?"],
            
            "th": ["ต้องการบัตรแขกสำหรับผู้มาเยี่ยมวันที่ {date} ชื่อ {guest} ค่ะ ต้องทำยังไงคะ"],
        },
        "hold": None,
        "resolve": {
            "en": "Register the guest in the app under Guests > Add (name + date). Reception will print a day pass; the first 4 guest days per month are free on your plan.",
            
            "th": "ลงทะเบียนแขกในแอปที่ Guests > Add (ชื่อ + วันที่) ค่ะ แผนกต้อนรับจะพิมพ์บัตรรายวันให้ 4 วันแรกต่อเดือนฟรีตามแพ็กเกจค่ะ",
        },
        "outcome": "informational",
    },
    {
        "topic": "ac_temperature", "intent": "too_cold",
        "ask": {
            "en": ["It's freezing in the open space, can the AC go up a bit?"],
            
            "th": ["โซนเปิดหนาวมากเลยค่ะ ปรับแอร์ให้อุ่นขึ้นหน่อยได้ไหมคะ"],
        },
        "hold": None,
        "resolve": None,   # unresolved: agent only acknowledges
        "unresolved_reply": {"en": "I'll ask facilities, hold on.",  "th": "ขอถามฝ่ายอาคารก่อนนะคะ"},
        "outcome": "unresolved",
    },
]

THANKS = {
    "en": ["Thanks!", "Great, thank you", "ok noted", "perfect, thanks a lot"],
    
    "th": ["ขอบคุณค่ะ", "ขอบคุณมากครับ", "โอเคค่ะ", "เยี่ยมเลย ขอบคุณนะคะ"],
}
GREET = {"en": ["Hi", "Hello!"],  "th": ["สวัสดีค่ะ", "สวัสดีครับ"]}

# Noise scenarios (should be dropped by the pipeline)
NOISE = [
    # agent-initiated broadcast + member compliance
    {"kind": "agent_initiated", "agent": {"en": "Reminder: please send a photo of your ID for the new access system by Friday.",
                                          
                                          "th": "แจ้งเตือน: รบกวนส่งรูปบัตรประชาชนสำหรับระบบเข้าออกใหม่ภายในวันศุกร์ค่ะ"},
     "member": {"en": "sent, please check",  "th": "ส่งแล้วค่ะ"}},
    # reminder to the agent (not a request for help)
    {"kind": "reminder", "member": {"en": "don't forget my locker key tomorrow",  "th": "อย่าลืมกุญแจล็อกเกอร์พรุ่งนี้นะคะ"}},
    # mid-thread reply with missing context
    {"kind": "mid_thread", "member": {"en": "yes I understand, but it still doesn't work",  "th": "เข้าใจค่ะ แต่ก็ยังใช้ไม่ได้"},
     "agent": {"en": "Try once more and tell me.",  "th": "ลองอีกครั้งแล้วบอกนะคะ"}},
    # greeting only
    {"kind": "greeting_only"},
]


def _fill(tmpl: str, rnd: random.Random, name: str) -> str:
    return tmpl.format(
        name=name,
        desk=rnd.randint(3, 48),
        time=f"{rnd.randint(8, 18):02d}:{rnd.choice(['00', '15', '30', '45'])}",
        date=f"{rnd.randint(1, 28):02d}.{rnd.randint(1, 12):02d}.2031",
        card=f"{rnd.randint(1000, 9999)} {rnd.randint(1000, 9999)} {rnd.randint(1000, 9999)}",
        amount=f"{rnd.choice([15, 25, 40, 60, 120, 310])} USD",
        email=f"{name.lower()}.{rnd.randint(10, 99)}@example.invalid",
        locker=rnd.randint(10, 60),
        code=rnd.randint(10, 99),
        guest=rnd.choice(["Ilse Varga", "Bao Nguyen", "Keiko Arai", "Omar Haddad"]),
    )


def generate(seed: int = 7, n_conversations: int = 40) -> list[dict]:
    rnd = random.Random(seed)
    out: list[dict] = []
    msg_id = 1000
    base_ts = 1_900_000_000  # arbitrary future epoch, no real timeline
    chat_clock: dict[str, int] = {}

    def emit(chat_id: str, from_id: str, role: str, text: str, ts: int, reply_to: int | None = None) -> int:
        nonlocal msg_id
        msg_id += 1
        out.append({"chat_id": chat_id, "msg_id": msg_id, "ts": ts, "from_id": from_id,
                    "from_role": role, "text": text, "reply_to": reply_to})
        return msg_id

    convs = 0
    noise_i = 0
    while convs < n_conversations:
        mid, mname, lang = MEMBERS[convs % len(MEMBERS)]
        chat_id = f"chat-{mid}"
        first = mname.split()[0]
        aid, _ = rnd.choice(AGENTS)
        ts = chat_clock.get(chat_id, base_ts + rnd.randint(0, 3600 * 24 * 5))
        ts += rnd.randint(3600 * 20, 3600 * 24 * 4)  # > 12h gap between threads

        # every 5th conversation is noise
        if convs % 5 == 4:
            nz = NOISE[noise_i % len(NOISE)]
            noise_i += 1
            if nz["kind"] == "agent_initiated":
                emit(chat_id, aid, "agent", nz["agent"][lang], ts)
                emit(chat_id, mid, "requester", nz["member"][lang], ts + 600)
            elif nz["kind"] == "reminder":
                emit(chat_id, mid, "requester", nz["member"][lang], ts)
                emit(chat_id, aid, "agent", {"en": "Sure.",  "th": "ได้ค่ะ"}[lang], ts + 300)
            elif nz["kind"] == "mid_thread":
                emit(chat_id, mid, "requester", nz["member"][lang], ts)
                emit(chat_id, aid, "agent", nz["agent"][lang], ts + 200)
            else:
                emit(chat_id, mid, "requester", rnd.choice(GREET[lang]), ts)
                emit(chat_id, aid, "agent", rnd.choice(GREET[lang]), ts + 120)
            chat_clock[chat_id] = ts + 900
            convs += 1
            continue

        sc = SCENARIOS[(convs * 7) % len(SCENARIOS)]
        if rnd.random() < 0.4:
            emit(chat_id, mid, "requester", rnd.choice(GREET[lang]), ts)
            ts += rnd.randint(20, 90)
        ask = _fill(rnd.choice(sc["ask"][lang]), rnd, first)
        if rnd.random() < 0.3:
            ask = ask + f" ({first}, {rnd.choice(['desk', 'desk', 'โต๊ะ'])} {rnd.randint(3, 48)})"
        q_id = emit(chat_id, mid, "requester", ask, ts)
        ts += rnd.randint(120, 1800)
        if sc.get("hold"):
            emit(chat_id, aid, "agent", sc["hold"][lang], ts, reply_to=q_id)
            ts += rnd.randint(300, 3600)
        if sc["resolve"]:
            emit(chat_id, aid, "agent", _fill(sc["resolve"][lang], rnd, first), ts, reply_to=q_id)
        else:
            emit(chat_id, aid, "agent", sc["unresolved_reply"][lang], ts, reply_to=q_id)
        ts += rnd.randint(60, 900)
        if rnd.random() < 0.8:
            emit(chat_id, mid, "requester", rnd.choice(THANKS[lang]), ts)
        chat_clock[chat_id] = ts
        convs += 1

    # one 3-party group chat with interleaved senders (dyad-rule demo)
    g_ts = base_ts + 3600 * 24 * 30
    emit("chat-group-01", "m-01", "requester", "Is anyone else getting kicked off the wifi on floor 3?", g_ts)
    emit("chat-group-01", "m-02", "requester", "Yes, same here since the morning", g_ts + 60)
    emit("chat-group-01", "a-01", "agent", "Looking into it, the access point is being restarted.", g_ts + 300)
    emit("chat-group-01", "m-01", "requester", "works now, thanks", g_ts + 900)

    out.sort(key=lambda r: (r["chat_id"], r["ts"], r["msg_id"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n", type=int, default=40)
    args = ap.parse_args()
    rows = generate(args.seed, args.n)
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} messages / {args.n} conversations -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
