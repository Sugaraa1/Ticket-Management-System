# Entity Relationship Diagram (ERD)

## Diagram

```mermaid
erDiagram
    USER ||--o{ TICKET : "reports"
    USER ||--o{ TICKET : "assigned_to"
    USER ||--o{ COMMENT : "writes"
    USER ||--o{ ATTACHMENT : "uploads"
    USER ||--o| PROFILE : "has"
    USER }o--o{ TEAM : "members"
    USER ||--o{ TEAM : "team_lead / qa_tester"
    USER ||--o{ STATUS_HISTORY : "changed_by"

    TEAM ||--o{ CATEGORY_TEAM_ASSIGNMENT : "assigned to"
    TEAM ||--o{ TICKET : "routed to"

    CATEGORY ||--o{ CATEGORY_TEAM_ASSIGNMENT : "has"
    CATEGORY ||--o{ TICKET : "classifies"

    PROJECT ||--o{ MODULE : "contains"
    PROJECT ||--o{ TICKET : "belongs to"
    MODULE ||--o{ TICKET : "belongs to"

    TICKET ||--o{ COMMENT : "has"
    TICKET ||--o{ ATTACHMENT : "has"
    TICKET ||--o{ STATUS_HISTORY : "tracks"

    USER {
        int id PK
        string username
        string email
        boolean is_active
        boolean is_superuser
    }

    PROFILE {
        int id PK
        int user_id FK
        image avatar
    }

    TEAM {
        int id PK
        string name
        int team_lead_id FK
        int qa_tester_id FK
    }

    CATEGORY {
        int id PK
        string name
        text description
    }

    CATEGORY_TEAM_ASSIGNMENT {
        int id PK
        int category_id FK
        int team_id FK
    }

    PROJECT {
        int id PK
        string name
        text description
        boolean is_active
    }

    MODULE {
        int id PK
        int project_id FK
        string name
    }

    TICKET {
        int id PK
        string title
        text description
        string ticket_type
        int category_id FK
        int project_id FK
        int module_id FK
        int team_id FK
        string status
        string priority
        int reported_by_id FK
        int assigned_to_id FK
        datetime sla_due_at
        datetime first_response_due_at
        datetime first_responded_at
        datetime last_activity_at
        datetime created_at
        datetime updated_at
    }

    COMMENT {
        int id PK
        int ticket_id FK
        int author_id FK
        text body
        boolean is_internal
        datetime created_at
    }

    ATTACHMENT {
        int id PK
        int ticket_id FK
        file file
        int uploaded_by_id FK
        datetime created_at
    }

    STATUS_HISTORY {
        int id PK
        int ticket_id FK
        string from_status
        string to_status
        int changed_by_id FK
        datetime changed_at
    }
```

## Entity тайлбар

### User
Django-ийн стандарт `User` модель. Эрхийг `role` талбараар биш, Django **Group**-оор ялгана (Admin / Project Manager / QA Tester / Developer). `is_active=False` бол нэвтрэх эрхгүй, ticket оноогдохгүй, харин түүх нь хадгалагдана (ticket-тэй хэрэглэгчийг устгах оронд идэвхгүй болгоно).

### Profile
User-тэй 1:1 холбоотой нэмэлт мэдээлэл — одоогоор зөвхөн профайлын зураг (`avatar`, 256×256 болгон тайрч хадгална).

### Team
Хөгжүүлэлтийн баг. `members` (M2M → User, Developer group), `team_lead` (ямар ч идэвхтэй хэрэглэгч), `qa_tester` (QA group) талбартай. Team Lead нь өөрийн багийн ticket дээр PM-ийн эрхтэй (оноох, хариуцагч/чухлын зэрэг солих, татгалзах, дахин нээх) болон багийн dashboard харна. Category бүр нэг буюу хэд хэдэн Team-тэй холбогдож болно (routing-д ашиглагдана).

### Category
Ticket-ийн ангилал (жишээ: "Backend API", "UI/UX", "Database"). Нэг Category **олон Team**-тэй холбогдож болно (CategoryTeamAssignment-аар).

### CategoryTeamAssignment
Category ↔ Team-ийн холбоос хүснэгт (`unique(category, team)`) — нэг Category олон Team-тэй байж болно. **Ticket auto-routing:** ticket үүсэхэд тухайн Category-ийн багуудаас хамгийн цөөн идэвхтэй ticket-тэй багийг сонгож `ticket.team`-д автоматаар онооно. Team Lead / QA Tester нь Team дээр тохируулагдана.

### Project / Module
Ticket аль төсөл, аль модультай холбоотойг заана. Module нь Project-ийн дэд түвшин (нэг төсөлд модулийн нэр давхцахгүй). `Project.is_active=False` бол шинэ ticket үүсгэх сонголтод гарахгүй. Ticket-тэй төслийг устгах боломжгүй (`PROTECT`) — оронд нь идэвхгүй болгоно. Module устгавал холбогдох ticket-ийн `module` хоосон болно (`SET_NULL`).

### Ticket
Системийн гол entity. `ticket_type` (bug/task/change_request), `status` (workflow дагуу), `priority` талбартай.

**SLA (Service Level Agreement):** Ticket үүсэх мөчид `priority`-с хамаарсан хариу үйлдэл хийх дээд хугацаа (`sla_due_at`) автоматаар тооцоологдож бичигдэнэ (тохиргоо: `settings.SLA_HOURS_BY_PRIORITY`):

| Priority | SLA хугацаа |
|---|---|
| CRITICAL | 4 цаг |
| HIGH | 1 өдөр (24 цаг) |
| MEDIUM | 3 өдөр (72 цаг) |
| LOW | 7 өдөр (168 цаг) |

SLA нь Jira Service Management-ийн адил 2 metric-тэй: **Time to First Response** (`first_response_due_at` / `first_responded_at`, `settings.SLA_FIRST_RESPONSE_HOURS_BY_PRIORITY`) ба **Time to Resolution** (`sla_due_at`). Priority өөрчлөгдвөл хоёулаа ticket үүссэн мөчөөс дахин тооцоологдоно. `last_activity_at` нь идэвхгүй ticket-ийн сануулгад (`check_stale_tickets`) ашиглагдана.

`Ticket.is_overdue` property нь `sla_due_at`-г одоогийн цагтай харьцуулж, ticket хугацаандаа шийдэгдээгүй эсэхийг тодорхойлно (CLOSED/REJECTED төлөвт байгаа ticket-д хамаарахгүй).

### Comment / Attachment
Ticket дээрх харилцан яриа, хавсаргасан файлууд.

**Internal note vs Public reply:** Comment дээр `is_internal` boolean талбар байгаа бөгөөд `True` бол зөвхөн дотоод багийн гишүүд (PM/QA/Developer/Admin) харах зориулалттай тэмдэглэл гэдгийг илэрхийлнэ (Zendesk/Freshdesk-ийн "Internal note" загвартай адилхан). Дотоод тэмдэглэлийг зөвхөн PM/Admin, ticket-ийн хариуцагч болон тухайн багийн гишүүн / Team Lead / QA Tester харж, бичнэ. Бусад хэрэглэгч (жишээ нь багт хамааралгүй мэдээлэгч) харахгүй, "Internal note" сонголт ч гарахгүй. UI дээр шар өнгө, 🔒 badge-аар ялгагдана. Гараар бичих сэтгэгдэл хоосон байж болохгүй; status шилжилтийн тайлбар л хоосон байж болно.

**Хавсралт файл** нь нийтэд нээлттэй `media/`-д биш `private_media/`-д хадгалагдаж, зөвхөн нэвтэрсэн хэрэглэгч `/attachments/<id>/` view-ээр татна (зураг, pdf, txt хөтөч дотор нээгдэнэ; бусад төрөл татагдана).

### StatusHistory
Ticket-ийн status өөрчлөгдөх бүрт бичигдэх audit trail — хэн, хэзээ, ямар төлөвөөс ямар төлөвт шилжүүлснийг хадгална.

## Шийдвэрлэгдсэн асуултууд
- **Эрх** — `User.role` талбар нэмэлгүй, Django Group-оор бүрэн орлуулсан.
- **Category ↔ Team** — нэг Category олон Team-тэй байж болно; ачааллаар routing хийнэ.
- **Attachment** — нэг файл хамгийн ихдээ 10MB, зөвшөөрөгдсөн өргөтгөлүүд `settings.ATTACHMENT_ALLOWED_EXTENSIONS`-д.
