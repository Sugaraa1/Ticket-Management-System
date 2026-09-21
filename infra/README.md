# Infra — Docker орчин

`docker-compose.yml` нь дараах 2 service-ийг ажиллуулна:

| Service | Тайлбар | Port |
|---|---|---|
| `db` | PostgreSQL 16 | 5432 |
| `web` | Django backend (migrate автоматаар ажилладаг + runserver) | 8000 |

## Ашиглах алхмууд

```bash
cd infra
cp .env.example .env        # шаардлагатай бол утгуудыг өөрчилнө
docker compose up --build
```

Анх удаа ажиллуулахад:
1. `db` контейнер Postgres-ийг эхлүүлж, healthy болохыг хүлээнэ
2. `web` контейнер автоматаар `python manage.py migrate` ажиллуулна (Group-ууд ч мөн үүснэ)
3. `http://localhost:8000/admin/` дээр Django admin нээгдэнэ

## Superuser үүсгэх

`web` контейнер ажиллаж байх зуур өөр terminal дээр:

```bash
docker compose exec web python manage.py createsuperuser
```

## Зогсоох / устгах

```bash
docker compose down          # зогсооно, DB өгөгдөл хадгалагдана (postgres_data volume)
docker compose down -v       # DB өгөгдлийг бүрмөсөн устгана
```

## backend/.env-тэй хамааралтай анхаарах зүйл

Хэрэв та **docker ашиглахгүйгээр** (Сонголт A/B-ээр) backend-ийг локал дээрээ шууд ажиллуулж байсан бол `backend/.env` доторх `DATABASE_URL`-ийг:

```
DATABASE_URL=postgres://ticket_user:ticket_pass@localhost:5432/ticket_db
```

гэж эргүүлж болно — учир нь одоо docker-ийн `db` service яг энэ user/password/db нэрээр Postgres-ийг өгч байгаа тул password authentication failed алдаа гарахгүй.

> **Анхаар:** локал (native) Postgres суулгасан бол `db` service-тэй **5432 port мөргөлдөж** болзошгүй тул `db` service-ийг **host дээр 5433** портоор гаргасан байгаа (`POSTGRES_HOST_PORT` хувьсагчаар өөрчилж болно). Энэ нь зөвхөн host → container холболтод хамаарна — `web` container өөрөө `db` service-тэй docker-ийн дотоод сүлжээгээр (`db:5432`) холбогддог тул `DATABASE_URL`-д нөлөөлөхгүй.
>
> Хэрэв host дээрээсээ (жишээ нь pgAdmin, DBeaver-ээр) DB-д холбогдох бол `localhost:5433` ашиглана.
