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
- Category бүрт Team Lead / QA Tester тохируулах
- Bug, Task, Change Request үүсгэх
- Category-д үндэслэн ticket-ийг автоматаар зөв багт чиглүүлэх
- Ticket-ийг хариуцсан ажилтанд оноох
- Priority, Status өөрчлөх
- Comment, Attachment нэмэх
- Ticket-ийн явцыг хянах (Status History)
- QA шалгалт хийх, шаардлагатай бол Reopen хийх
- Dashboard болон тайлангаар мэдээлэл харах

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

## 7. Холбоотой баримтууд
- [`docs/ERD.md`](./ERD.md) — Өгөгдлийн сангийн бүтэц
- [`docs/workflow.md`](./workflow.md) — Ticket-ийн төлөв шилжилт
