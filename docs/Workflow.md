Ticket Workflow
Diagram
NEW

ASSIGNED

IN PROGRESS

RESOLVED

REJECTED

QA TEST

CLOSED

REOPENED

Status тодорхойлолт
Status	Тайлбар
NEW	Ticket шинээр үүссэн, хараахан хариуцагчгүй
ASSIGNED	Category-ийн дагуу team рүү чиглэгдэж, хариуцах ажилтан оноогдсон
IN_PROGRESS	Developer/Agent ажиллаж эхэлсэн
RESOLVED	Developer шийдвэрлэсэн гэж тэмдэглэсэн
REJECTED	Ticket хүчингүй/давхардсан/буруу гэж татгалзсан (шаардлагатай бол дахин нээгдэж болно)
QA_TEST	QA шалгаж байгаа
REOPENED	QA дахин нээсэн (шийдэл хангалтгүй)
CLOSED	QA баталгаажуулж хаасан
Зөвшөөрөгдсөн шилжилтүүд (Allowed Transitions)
Одоогийн Status	Боломжит дараагийн Status	Хийж болох эрх
NEW	ASSIGNED	PM/Team Lead
ASSIGNED	IN_PROGRESS	Developer/Agent
IN_PROGRESS	RESOLVED	Developer/Agent
IN_PROGRESS	REJECTED	Developer/Agent, PM/Team Lead
RESOLVED	QA_TEST	Developer/Agent ("QA-д илгээх" товч дарж, гараар)
QA_TEST	CLOSED	QA
QA_TEST	REOPENED	QA (comment сонголтоор — заавал биш)
REOPENED	IN_PROGRESS	Developer/Agent
REJECTED	REOPENED	PM/Team Lead
Дээрх хүснэгтэд байхгүй шилжилт (жишээ нь NEW → CLOSED) программаар хориглогдоно. RESOLVED → QA_TEST шилжилт нь гар аргаар хийгдэнэ (Django signal-аар автоматаар шилжихгүй) — Developer "Илгээх QA-д" товч дарж явуулна.

Хэрэгжүүлэлтийн санал (Django)
ALLOWED_TRANSITIONS = {
    "new": ["assigned"],
    "assigned": ["in_progress"],
    "in_progress": ["resolved", "rejected"],
    "resolved": ["qa_test"],
    "qa_test": ["closed", "reopened"],
    "reopened": ["in_progress"],
    "rejected": ["reopened"],
    "closed": [],
}

def can_transition(current_status: str, new_status: str) -> bool:
    return new_status in ALLOWED_TRANSITIONS.get(current_status, [])
Status өөрчлөгдөх бүрд StatusHistory бичлэг үүсгэж, from_status, to_status, changed_by, changed_at-ийг хадгална.

Comment заавал эсэх (Reopen дээр)
QA_TEST → REOPENED болон REJECTED → REOPENED шилжилт хийхэд comment заавал биш, сонголтоор. UI дээр comment оруулах талбар харагдана, гэхдээ хоосон орхиод шууд submit хийж болно (Comment.body заавал биш blank=True байдлаар models дээр тохируулна).