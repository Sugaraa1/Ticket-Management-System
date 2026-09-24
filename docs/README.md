# Ticket Management System

## 1. Төслийн зорилго
Программ хангамж хөгжүүлэлтийн явцад гарсан **bug**, **task**, **change request**-ийг ticket хэлбэрээр бүртгэж, тухайн асуудал хамаарах **project**, **module** болон хариуцсан ажилтныг тодорхойлон, холбогдох ажилтанд оноож, шийдвэрлэлтийн явцыг хянах систем.

## 2. Repo бүтэц

```
Ticket-Management-System/
├── backend/    # Django + DRF-ready backend
├── docs/       # Requirement, ERD, workflow, API баримт
└── infra/      # Docker, docker-compose, deployment
```

## 3. Технологийн сонголт

| Давхарга | Технологи |
|---|---|
| Backend | Python + Django |
| Database | PostgreSQL |
| Frontend | Django Templates + Bootstrap |
| Auth | Django Authentication + Groups & Permissions |
| Email | Django `send_mail` |
| VCS | Git + GitHub |
| Dev OS | Ubuntu Linux |
| API Testing | Postman |

**Ирээдүйн өргөтгөл:** Django REST Framework + React, Celery + Redis.

## 4. Үндсэн үйл ажиллагаа
- Category болон баг (Team) бүртгэх
- Team бүрт Team Lead / QA Tester тохируулах, category-г тухайн team рүү routing хийх
- Bug, Task, Change Request үүсгэх
- Category-д үндэслэн ticket-ийг автоматаар зөв багт чиглүүлэх
- Ticket-ийг хариуцсан ажилтанд оноох
- Priority, Status өөрчлөх
- Comment, Attachment нэмэх
- Ticket-ийн явцыг хянах (Status History)
- QA шалгалт хийх, шаардлагатай бол Reopen хийх
- Dashboard болон тайлангаар мэдээлэл харах
- Ticket жагсаалтыг pagination-тай харах (25 мөр/хуудас), enterprise service-desk (жишээ нь Jira Service Management/Rakuten Lab Manager) загварчилсан toolbar-аар хайх/шүүх: гарчгаар хайх талбар, идэвхтэй үед цэгээр тэмдэглэгддэг collapsible шүүлтүүр (Төлөв/Чухлын зэрэг/Ангилал), "Нийт X ticket-ээс Y–Z-г харуулж байна" тоолуур
- Ticket үүсэх (routing), оноогдох, status шилжихэд холбогдох хэрэглэгчдэд email мэдэгдэл илгээх
- Хэрэглэгч интерфэйсийн хэлийг Монгол/Англи (MN/EN) хооронд сонгож солих
- SLA policy + escalation automation (Jira Service Management загвартай): Time to First Response / Time to Resolution гэсэн 2 metric-ийг хянаж, хугацаа дуусахад ойртоход анхааруулга, хэтэрвэл Team Lead рүү escalation мэдэгдэл автоматаар илгээх (`docs/workflow.md`-г үзнэ үү)
- Automation rule (Zendesk/Jira загвартай): идэвхгүй байдал үргэлжилж буй ticket-д N цаг тутамд давтан сануулга илгээх
- Navbar → Удирдлага цэснээс дээрх 2 automation-ыг PM/Admin гар аргаар шууд тестлэх боломжтой ("SLA шалгалт ажиллуулах" / "Идэвхгүй ticket шалгах" товч)
- Reporting dashboard (Zendesk/Jira загвартай, `/reports/`): 7/30/90 хоногийн хугацаагаар SLA compliance %, ticket volume trend (үүссэн/хаагдсан), ажилтны гүйцэтгэл, priority/category-аар задаргаа харах (`docs/workflow.md`-г үзнэ үү)

## 5. Хэрэглэгчийн эрх (Django Groups)

| Group | Эрх |
|---|---|
| Admin | Систем, хэрэглэгч, эрхийн удирдлага |
| Project Manager / Team Lead | Project, module, ticket удирдах |
| QA / Tester | Bug илрүүлж ticket үүсгэх, дахин шалгах |
| Developer / Agent | Өөрт оноогдсон ticket-ийг шийдвэрлэх |

## 6. Локал орчинд ажиллуулах (төлөвлөгөө)
1. `infra/` доторх `docker-compose.yml`-ээр PostgreSQL контейнер ажиллуулах
2. `backend/` дотор virtualenv үүсгэж, `pip install -r requirements.txt`
3. `.env` файл тохируулах (DB холболт, SECRET_KEY)
4. `python manage.py migrate`
5. `python manage.py createsuperuser`
6. `python manage.py runserver`

> Дэлгэрэнгүй алхмуудыг `infra/` бэлэн болмогц энд шинэчилнэ.

## 7. Тест ажиллуулах

```
cd backend
python manage.py test
```

`apps/tickets/tests/` болон `apps/categories/tests.py` дотор workflow шилжилт, SLA тооцоолол, эрхийн шалгалт, email мэдэгдэл, ticket жагсаалтын pagination зэргийг хамарсан unit/view тестүүд байна.

## 8. Хэл (MN/EN) — i18n

Navbar-ийн сонголтоос хэл солиход бүх хуудас, form label, статус нэр, мэдэгдэл орчуулагдана. Орчуулгын эх сурвалж (Монгол) → англи хөрвүүлэлт `backend/locale/en/LC_MESSAGES/django.po` файлд байна.

Шинэ текст нэмэх/өөрчлөх бүрд:

```
cd backend
python manage.py makemessages -l en   # шинэ msgid-үүдийг django.po-д нэмнэ
# locale/en/LC_MESSAGES/django.po дотор хоосон msgstr-үүдийг орчуулах
python manage.py compilemessages -l en
```

## 9. Холбоотой баримтууд
- [`docs/ERD.md`](./ERD.md) — Өгөгдлийн сангийн бүтэц
- [`docs/workflow.md`](./workflow.md) — Ticket-ийн төлөв шилжилт
