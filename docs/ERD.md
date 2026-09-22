# Entity Relationship Diagram (ERD)

## Diagram

```mermaid
erDiagram
    USER ||--o{ TICKET : "reports"
    USER ||--o{ TICKET : "assigned_to"
    USER ||--o{ COMMENT : "writes"
    USER ||--o{ ATTACHMENT : "uploads"
    USER ||--o{ CATEGORY_TEAM_ASSIGNMENT : "team_lead / qa_tester"

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
        string role
    }

    TEAM {
        int id PK
        string name
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
        int team_lead_id FK
        int qa_tester_id FK
    }

    PROJECT {
        int id PK
        string name
        text description
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
        datetime uploaded_at
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
Django-ийн стандарт `User` эсвэл `AbstractUser`-аас өргөтгөсөн custom модель. Group-оор эрх ялгах (Admin / PM-TeamLead / QA / Developer).

### Team
Хөгжүүлэлтийн баг. Category бүр нэг буюу хэд хэдэн Team-тэй холбогдож болно (routing-д ашиглагдана).

### Category
Ticket-ийн ангилал (жишээ: "Backend API", "UI/UX", "Database"). Category бүрт Team Lead болон QA Tester тохируулагдана.

### CategoryTeamAssignment
Category ↔ Team-ийн холбоос хүснэгт. `team_lead`, `qa_tester` талбарууд нь тухайн category-д хариуцлагатай хүмүүсийг заана. **Ticket auto-routing** энэ хүснэгтээс уншиж, category-д тохирох team-ийг ticket дээр автоматаар онооно.

### Project / Module
Ticket аль төсөл, аль модультай холбоотойг заана. Module нь Project-ийн дэд түвшин.

### Ticket
Системийн гол entity. `ticket_type` (bug/task/change_request), `status` (workflow дагуу), `priority` талбартай.

**SLA (Service Level Agreement):** Ticket үүсэх мөчид `priority`-с хамаарсан хариу үйлдэл хийх дээд хугацаа (`sla_due_at`) автоматаар тооцоологдож бичигдэнэ (тохиргоо: `settings.SLA_HOURS_BY_PRIORITY`):

| Priority | SLA хугацаа |
|---|---|
| CRITICAL | 4 цаг |
| HIGH | 1 өдөр (24 цаг) |
| MEDIUM | 3 өдөр (72 цаг) |
| LOW | 7 өдөр (168 цаг) |

`Ticket.is_overdue` property нь `sla_due_at`-г одоогийн цагтай харьцуулж, ticket хугацаандаа шийдэгдээгүй эсэхийг тодорхойлно (CLOSED/REJECTED төлөвт байгаа ticket-д хамаарахгүй).

### Comment / Attachment
Ticket дээрх харилцан яриа, хавсаргасан файлууд.

**Internal note vs Public reply:** Comment дээр `is_internal` boolean талбар байгаа бөгөөд `True` бол зөвхөн дотоод багийн гишүүд (PM/QA/Developer/Admin) харах зориулалттай тэмдэглэл гэдгийг илэрхийлнэ (Zendesk/Freshdesk-ийн "Internal note" загвартай адилхан). Одоогийн хувилбарт энэ талбар зөвхөн **UI дээр тусгайлан тэмдэглэгдэж харагдана** (шар өнгөөр тодруулсан, 🔒 badge-тай) — ирээдүйд гадаад (customer-facing) портал нэмэгдвэл харагдах эрхийг хязгаарлахад ашиглана.

### StatusHistory
Ticket-ийн status өөрчлөгдөх бүрт бичигдэх audit trail — хэн, хэзээ, ямар төлөвөөс ямар төлөвт шилжүүлснийг хадгална.

## Тодруулга, шийдвэрлэх шаардлагатай асуултууд
- `User.role` талбарыг Django Group-оор бүрэн орлуулах уу, эсвэл нэмэлт `Profile.role` талбар хэрэгтэй юу?
- Нэг Category хэд хэдэн Team-тэй байж болох уу (олон нийтийн routing), эсвэл 1:1 харьцаа хангалттай юу?
- Attachment-ийн файлын хэмжээ/төрлийн хязгаарлалт хэрэгтэй юу (жишээ: зөвхөн зураг, max 10MB)?
