# Entity Relationship Diagram (ERD)

## Diagram

```mermaid
erDiagram
    USER ||--o{ TICKET : "reports"
    USER ||--o{ TICKET : "assigned_to"
    USER ||--o{ COMMENT : "writes"
    USER ||--o{ ATTACHMENT : "uploads"
    USER ||--o{ TEAM : "team_lead / qa_tester"

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
        datetime sla_warning_sent_at
        datetime sla_breach_notified_at
        datetime first_response_due_at
        datetime first_responded_at
        datetime first_response_warning_sent_at
        datetime first_response_breach_notified_at
        datetime last_activity_at
        datetime stale_reminder_sent_at
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
Хөгжүүлэлтийн баг. `team_lead`, `qa_tester` талбарууд нь тухайн багийг хариуцах хүмүүсийг заана (баг үүсгэх/засах үед тохируулагдана). Category бүр нэг буюу хэд хэдэн Team-тэй холбогдож болно (routing-д ашиглагдана).

### Category
Ticket-ийн ангилал (жишээ: "Backend API", "UI/UX", "Database").

### CategoryTeamAssignment
Category ↔ Team-ийн холбоос хүснэгт. **Ticket auto-routing** энэ хүснэгтээс уншиж, category-д тохирох team-ийг ticket дээр автоматаар онооно. Хариуцах Team Lead/QA Tester нь холбогдсон Team-ээс тодорхойлогдоно.

### Project / Module
Ticket аль төсөл, аль модультай холбоотойг заана. Module нь Project-ийн дэд түвшин.

### Ticket
Системийн гол entity. `ticket_type` (bug/task/change_request), `status` (workflow дагуу), `priority` талбартай.

**SLA (Service Level Agreement):** Jira Service Management-ийн загвартай 2 тусдаа metric ашиглана — дэлгэрэнгүйг [`docs/workflow.md`](./workflow.md#sla-policy--escalation-automation-jira-service-management-загвартай)-с үзнэ үү:

| Priority | Time to First Response | Time to Resolution |
|---|---|---|
| CRITICAL | 1 цаг | 4 цаг |
| HIGH | 4 цаг | 1 өдөр (24 цаг) |
| MEDIUM | 8 цаг | 3 өдөр (72 цаг) |
| LOW | 1 өдөр (24 цаг) | 7 өдөр (168 цаг) |

`Ticket.is_overdue` / `Ticket.is_first_response_overdue` properties нь тухайн due date-г одоогийн цагтай харьцуулна (CLOSED/REJECTED төлөвт байгаа ticket-д хамаарахгүй). `apps.tickets.management.commands.check_sla_deadlines` command нь эдгээрийг үечлэн шалгаж, хугацаа дуусахад ойртоход анхааруулга, хэтэрвэл Team Lead рүү escalation email автоматаар илгээнэ.

**Automation rule (идэвхгүй ticket):** `last_activity_at` талбар нь status шилжилт/comment/attachment бүрд шинэчлэгдэнэ. `apps.tickets.management.commands.check_stale_tickets` command нь `settings.STALE_TICKET_REMINDER_HOURS`-аас удаан идэвхгүй байсан ticket-д хариуцагч (эсвэл Team Lead) руу давтан сануулга илгээнэ (`stale_reminder_sent_at`-аар давхардлаас сэргийлнэ) — дэлгэрэнгүйг [`docs/workflow.md`](./workflow.md#automation-rule-идэвхгүй-ticket-д-давтан-сануулга-zendeskjira-загвартай)-с үзнэ үү.

### Comment / Attachment
Ticket дээрх харилцан яриа, хавсаргасан файлууд.

**Internal note vs Public reply:** Comment дээр `is_internal` boolean талбар байгаа бөгөөд `True` бол зөвхөн дотоод багийн гишүүд (PM/QA/Developer/Admin) харах зориулалттай тэмдэглэл гэдгийг илэрхийлнэ (Zendesk/Freshdesk-ийн "Internal note" загвартай адилхан). Одоогийн хувилбарт энэ талбар зөвхөн **UI дээр тусгайлан тэмдэглэгдэж харагдана** (шар өнгөөр тодруулсан, 🔒 badge-тай) — ирээдүйд гадаад (customer-facing) портал нэмэгдвэл харагдах эрхийг хязгаарлахад ашиглана.

### StatusHistory
Ticket-ийн status өөрчлөгдөх бүрт бичигдэх audit trail — хэн, хэзээ, ямар төлөвөөс ямар төлөвт шилжүүлснийг хадгална.

## Тодруулга, шийдвэрлэх шаардлагатай асуултууд
- `User.role` талбарыг Django Group-оор бүрэн орлуулах уу, эсвэл нэмэлт `Profile.role` талбар хэрэгтэй юу?
- Нэг Category хэд хэдэн Team-тэй байж болох уу (олон нийтийн routing), эсвэл 1:1 харьцаа хангалттай юу?
- Attachment-ийн файлын хэмжээ/төрлийн хязгаарлалт хэрэгтэй юу (жишээ: зөвхөн зураг, max 10MB)?
