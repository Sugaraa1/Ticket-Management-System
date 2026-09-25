# Ticket Management System

## 1. Төслийн зорилго
Программ хангамж хөгжүүлэлтийн явцад гарсан **bug**, **task**, **change request**-ийг ticket хэлбэрээр бүртгэж, тухайн асуудал хамаарах **project**, **module** болон хариуцсан ажилтныг тодорхойлон, холбогдох ажилтанд оноож, шийдвэрлэлтийн явцыг хянах систем.

## 2. Repo бүтэц

```
Ticket-Management-System/
├── backend/    # Django backend (apps: accounts, categories, core, projects, tickets)
├── docs/       # ERD, workflow баримт
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
- Team бүрт Team Lead / QA Tester тохируулах; нэг Category-г олон багт холбож болно (хамгийн бага ачаалалтай баг руу автоматаар routing)
- Bug, Task, Change Request үүсгэх
- Category-д үндэслэн ticket-ийг автоматаар зөв багт чиглүүлэх
- Ticket-ийг хариуцсан ажилтанд оноох
- Priority, Status өөрчлөх
- Ticket засах (гарчиг, тайлбар, төрөл, төсөл, модуль; ангиллыг зөвхөн "Шинэ" төлөвт — баг дахин автоматаар сонгогдоно): мэдээлэгч, PM/Admin, багийн Team Lead; хаагдсан/татгалзсан ticket засагдахгүй, өөрчлөлт бүр сэтгэгдэлд бүртгэгдэнэ
- **Бөөнөөр үйлдэл** (зөвхөн PM / Admin) — ticket жагсаалтаас checkbox-оор олон ticket сонгож нэг дор оноох / хариуцагч солих, чухлын зэрэг, төлөв шилжүүлэх; ticket бүр дээр ticket-ийн хуудастай ижил эрхийн шалгалт хийгдэж, боломжгүйг нь шалтгаантай нь алгасна (`apps/tickets/actions.py`)
- **@mention** — сэтгэгдэлд `@username` бичвэл тухайн хүнд мэйл очно (бичих үед нэр санал болгоно); шинэ сэтгэгдлийн мэйл мэдээлэгч, хариуцагчид очно; дотоод тэмдэглэлийн мэдэгдэл зөвхөн харах эрхтэй хүнд очно
- "Нууц үгээ мартсан уу?" — бүртгэлтэй и-мэйл рүү 24 цагийн, нэг удаагийн сэргээх линк (SMTP тохируулсан байх шаардлагатай)
- Comment, Attachment нэмэх
- Ticket-ийн явцыг хянах (Status History)
- QA шалгалт хийх, шаардлагатай бол Reopen хийх
- "Миний ажил" (профайл) хуудас — эрхээс хамаарсан ажлын дараалал: Developer → надад оноогдсон; QA Tester → өөрийн багийн "Чанарын шалгалтад" ирсэн ticket; Team Lead → өөрийн багт ирсэн, оноогдоогүй ticket; мөн миний мэдээлсэн ticket, SLA хэтэрсэн тоо. Sidebar дээрх улаан badge нь өөрөөс үйлдэл хүлээж буй ticket-ийн тоо
- Email мэдэгдэл: ticket үүсэхэд үүсгэсэн хүнд баталгаажуулалт, багийн Team Lead-д "шинэ ticket"; оноогдоход хариуцагчид; ticket "Чанарын шалгалтад" орвол багийн QA Tester-т, Шийдэгдсэн/Татгалзсан/Дахин нээгдсэн/Хаагдсан болбол Team Lead-д очно
- Хавсралт: нэг файл хамгийн ихдээ 10MB, зөвшөөрөгдсөн төрөл (зураг, pdf, office, txt/log/csv/json, zip) — `settings.ATTACHMENT_MAX_SIZE_MB`, `ATTACHMENT_ALLOWED_EXTENSIONS`; ticket үүсгэх үед шууд файл хавсаргаж болно
- UI: зүүн sidebar-тай орчин үеийн layout (Bootstrap 5 + Bootstrap Icons), гар утсан дээр sidebar эвхэгддэг
- Ticket жагсаалт (Lab Manager / Jira маягийн): Төлөв, ID, Гарчиг, Чухлын зэрэг, Хариуцагч, Үүсгэсэн/Шинэчилсэн огноо, Мэдээлсэн, Дуусах огноо (SLA), Ангилал баганууд; хайлт + collapsible шүүлтүүр
- "+ Шинэ ticket" товч хуудас шилжихгүйгээр баруун талаас гарч ирэх маягт (drawer) нээнэ; чухлын зэрэг сонгоход SLA хугацаа (хариу/шийдвэрлэлт) харагдана
- PM/Admin ticket-ийн чухлын зэргийг өөрчлөх боломжтой — SLA хугацаа ticket үүссэн мөчөөс шинэ зэргээр дахин тооцоологдож, өөрчлөлт сэтгэгдэлд бүртгэгдэнэ
- **SLA** — Time to First Response ба Time to Resolution (priority-оос хамаарна); хугацаанд ойртох/хэтрэхэд email анхааруулга (`check_sla_deadlines`), идэвхгүй ticket-ийн давтан сануулга (`check_stale_tickets`)
- **Хариуцагч солих** — PM/Admin эсвэл багийн Team Lead оноогдсон ticket-ийг багийн өөр идэвхтэй гишүүнд шилжүүлнэ
- **Dashboard (тайлан)** — 7/30/90 хоногийн SLA биелэлт %, ticket-ийн урсгал, ажилтны гүйцэтгэл, чухлын зэрэг/ангиллын задаргаа. Admin/PM нийт болон дурын багийнхыг (баг сонгогчоор), Team Lead зөвхөн өөрийн багийнхыг "Миний баг" хуудаснаас харна
- **Экспорт** — Dashboard-оос Excel (олон sheet) / CSV / PDF (хэвлэх), ticket жагсаалтаас одоогийн шүүлтүүрээр Excel / CSV (Admin/PM бүгдийг, Team Lead зөвхөн өөрийн багийнхыг)
- **Удирдлага** (PM/Admin) — Хэрэглэгч (зөвхөн Admin: бүртгэх, засах, эрх/нууц үг солих, идэвхтэй/идэвхгүй toggle, устгах), Төсөл/Модуль (нэмэх, засах, устгах, идэвхтэй toggle), Ангилал, Баг. Жагсаалт бүр хайлт, шүүлтүүр, эрэмбэ, хуудаслалттай
- **Устгах/идэвхгүй болгох** бүх үйлдэл сайтын загвартай баталгаажуулах цонхтой; ticket-ийн түүхтэй хэрэглэгч/төслийг устгах оронд идэвхгүй болгоно
- Хавсралт файлууд нийтэд нээлттэй биш (`private_media/`), зөвхөн нэвтэрсэн хэрэглэгч татна; дотоод тэмдэглэл зөвхөн багт харагдана
- Профайлын зураг ("Миний ажил" хуудасны зураг дээр дарж солино)
- Монгол / англи хэл (`locale/en`)

## 5. Хэрэглэгчийн эрх (Django Groups)

| Group | Эрх |
|---|---|
| Admin | Бүх эрх: хэрэглэгч удирдах, бүх шилжилт, нийт dashboard/экспорт |
| Project Manager | Төсөл, ангилал, баг удирдах; ticket оноох, хариуцагч/чухлын зэрэг солих; нийт dashboard/экспорт |
| Team Lead | Group биш — багийн `team_lead` талбараар тодорхойлогдоно (ямар ч хэрэглэгчийг томилж болно): өөрийн багийн ticket-ийг оноох, хариуцагч / чухлын зэрэг солих, татгалзах / дахин нээх, багийн dashboard, багийн ticket-ийн экспорт |
| QA Tester | Өөрийн багийн "Чанарын шалгалтад" ticket-ийг хаах / дахин нээх |
| Developer | Өөрт оноогдсон ticket-ийг шийдвэрлэх |

Ticket үүсгэх, жагсаалт харах эрх нэвтэрсэн бүх хэрэглэгчид бий.

## 6. Локал орчинд ажиллуулах

**Docker-оор (санал болгох):** [`infra/README.md`](../infra/README.md)-г үзнэ үү (`docker compose up --build`, migrate автоматаар ажиллана).

**Docker-гүйгээр:**
1. `cd backend && python -m venv .venv && . .venv/bin/activate`
2. `pip install -r requirements.txt` (Excel экспортод `openpyxl` орсон)
3. `.env` файл тохируулах (`DATABASE_URL`, `SECRET_KEY`; `DATABASE_URL` заагаагүй бол SQLite ашиглана)
4. `python manage.py migrate`
5. `python manage.py createsuperuser`
6. `python manage.py runserver`

**Тест:** `python manage.py test apps`

**Email илгээх:** `backend/.env`-д `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`-ийг бөглөнө (Gmail бол App password). `EMAIL_HOST` заагаагүй бол мэйл явахгүй, зөвхөн серверийн лог руу хэвлэгдэнэ. Хүлээн авагч хэрэглэгчийн профайлд и-мэйл хаяг бүртгэлтэй байх ёстой. Илгээхэд алдаа гарвал `docker compose logs web`-д харагдана.

**SLA мэдэгдэл (тогтмол шалгалт):** Docker-т `scheduler` service автоматаар ажиллана. Docker-гүй бол тусдаа terminal дээр `python manage.py run_scheduler` (15 мин тутам `check_sla_deadlines`, 60 мин тутам `check_stale_tickets`), эсвэл cron-оор тус тусад нь дуудна.

**Production:** `DJANGO_SETTINGS_MODULE=config.settings.prod`, `.env`-д жинхэнэ `SECRET_KEY` заавал (default түлхүүрээр асахгүй), `ALLOWED_HOSTS`, SMTP тохиргоо.

## 7. Холбоотой баримтууд
- [`docs/ERD.md`](./ERD.md) — Өгөгдлийн сангийн бүтэц
- [`docs/workflow.md`](./workflow.md) — Ticket-ийн төлөв шилжилт
