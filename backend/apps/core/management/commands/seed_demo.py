"""
Туршилт / танилцуулгад зориулсан бодит мэт demo өгөгдөл үүсгэнэ.

    python manage.py seed_demo            # байхгүй бол үүсгэнэ (дахин ажиллуулахад давхардахгүй)
    python manage.py seed_demo --password Demo12345

Хэрэглэгч, баг, ангилал, төсөл/модуль-ийг нэрээр нь get_or_create хийнэ; ticket-үүдийг
зөвхөн demo хэрэглэгчдийн ticket хараахан байхгүй үед үүсгэнэ. Ticket-үүдийн огноог
сүүлийн 60 хоногт тарааж, төлөвийн түүх / SLA / сэтгэгдлийг тэр огноонд тааруулна —
Dashboard-ийн SLA биелэлт, урсгал, ажилтны гүйцэтгэл бодит харагдана. Мэйл илгээхгүй.
"""
import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.categories.models import Category, CategoryTeamAssignment, Team
from apps.projects.models import Module, Project
from apps.tickets.models import Comment, StatusHistory, Ticket
from apps.tickets.permissions import ROLE_ADMIN, ROLE_DEV, ROLE_PM, ROLE_QA

USERS = [
    # username, овог, нэр, эрх
    ("bat.pm", "Батбаяр", "Ганбаатар", ROLE_PM),
    ("saraa.pm", "Сараа", "Дорж", ROLE_PM),
    ("temuulen", "Тэмүүлэн", "Бат", ROLE_DEV),
    ("anu", "Ану", "Мөнх", ROLE_DEV),
    ("bilguun", "Билгүүн", "Эрдэнэ", ROLE_DEV),
    ("nomin", "Номин", "Цэрэн", ROLE_DEV),
    ("khulan", "Хулан", "Отгон", ROLE_DEV),
    ("erdene", "Эрдэнэ", "Сүх", ROLE_DEV),
    ("oyuka.qa", "Оюунаа", "Жаргал", ROLE_QA),
    ("munkh.qa", "Мөнх-Очир", "Лхагва", ROLE_QA),
    ("zaya.admin", "Заяа", "Нямаа", ROLE_ADMIN),
]

TEAMS = {
    # нэр: (Team Lead, QA, гишүүд)
    "Backend баг": ("bat.pm", "oyuka.qa", ["temuulen", "anu", "bilguun"]),
    "Frontend баг": ("temuulen", "munkh.qa", ["nomin", "khulan"]),
    "Mobile баг": ("saraa.pm", "oyuka.qa", ["erdene", "khulan"]),
}

CATEGORIES = {
    # нэр: (тайлбар, багууд)
    "Backend API": ("REST API, бизнес логик, интеграци", ["Backend баг"]),
    "Өгөгдлийн сан": ("Query удаашрал, migration, өгөгдлийн алдаа", ["Backend баг"]),
    "Вэб интерфэйс": ("Вэб хуудасны харагдац, UX", ["Frontend баг"]),
    "Mobile апп": ("iOS / Android аппликейшн", ["Mobile баг"]),
    "Аюулгүй байдал": ("Нэвтрэлт, эрх, эмзэг байдал", ["Backend баг", "Frontend баг"]),
}

PROJECTS = {
    # нэр: (тайлбар, идэвхтэй эсэх, модулиуд)
    "Интернет банк": ("Хувь хүний интернет банкны систем", True, ["Нэвтрэлт", "Гүйлгээ", "Карт", "Хуулга"]),
    "HR систем": ("Хүний нөөцийн удирдлагын систем", True, ["Цалин", "Ирц", "Ажилтны бүртгэл"]),
    "Цахим дэлгүүр": ("Онлайн худалдааны платформ", True, ["Сагс", "Төлбөр", "Бүтээгдэхүүн", "Хүргэлт"]),
    "Хуучин CRM": ("2019 оны CRM — шинэ систем рүү шилжсэн", False, ["Харилцагч"]),
}

# (гарчиг, төрөл, чухлын зэрэг, ангилал, төсөл, модуль, эцсийн төлөв)
TICKETS = [
    ("Нэвтрэх үед 500 алдаа гарч байна", "bug", "critical", "Backend API", "Интернет банк", "Нэвтрэлт", "closed"),
    ("Гүйлгээний түүх удаан ачаалж байна", "bug", "high", "Өгөгдлийн сан", "Интернет банк", "Хуулга", "closed"),
    ("Картын лимит өөрчлөх API нэмэх", "task", "medium", "Backend API", "Интернет банк", "Карт", "closed"),
    ("Нууц үг сэргээх мэйл ирэхгүй байна", "bug", "high", "Backend API", "Интернет банк", "Нэвтрэлт", "closed"),
    ("Хуулгыг PDF-ээр татах боломж", "cr", "low", "Вэб интерфэйс", "Интернет банк", "Хуулга", "closed"),
    ("Гүйлгээ давхар бүртгэгдэж байна", "bug", "critical", "Өгөгдлийн сан", "Интернет банк", "Гүйлгээ", "closed"),
    ("Хоёр шатлалт баталгаажуулалт (2FA)", "cr", "high", "Аюулгүй байдал", "Интернет банк", "Нэвтрэлт", "qa_test"),
    ("Гар утсан дээр гүйлгээний товч харагдахгүй", "bug", "medium", "Mobile апп", "Интернет банк", "Гүйлгээ", "in_progress"),
    ("Сессийн хугацаа дуусахад анхааруулга гаргах", "task", "low", "Вэб интерфэйс", "Интернет банк", "Нэвтрэлт", "new"),
    ("SQL injection эрсдэл — хайлтын талбар", "bug", "critical", "Аюулгүй байдал", "Интернет банк", "Хуулга", "resolved"),
    ("Цалингийн тооцоонд татвар буруу бодогдож байна", "bug", "critical", "Backend API", "HR систем", "Цалин", "closed"),
    ("Ирцийн тайланг Excel-ээр гаргах", "task", "medium", "Вэб интерфэйс", "HR систем", "Ирц", "closed"),
    ("Ажилтны зураг upload хийхэд алдаа", "bug", "medium", "Backend API", "HR систем", "Ажилтны бүртгэл", "reopened"),
    ("Ээлжийн амралтын хүсэлтийн урсгал", "cr", "medium", "Backend API", "HR систем", "Ирц", "in_progress"),
    ("Цалингийн хуудас гар утсанд эвдэрч харагдана", "bug", "low", "Mobile апп", "HR систем", "Цалин", "assigned"),
    ("Ажилтны жагсаалтад хайлт нэмэх", "task", "low", "Вэб интерфэйс", "HR систем", "Ажилтны бүртгэл", "closed"),
    ("Ирцийн төхөөрөмжөөс өгөгдөл ирэхгүй", "bug", "high", "Өгөгдлийн сан", "HR систем", "Ирц", "rejected"),
    ("Сагсанд бараа нэмэхэд тоо шинэчлэгдэхгүй", "bug", "high", "Вэб интерфэйс", "Цахим дэлгүүр", "Сагс", "closed"),
    ("QPay төлбөрийн интеграци", "task", "high", "Backend API", "Цахим дэлгүүр", "Төлбөр", "closed"),
    ("Төлбөр амжилттай ч захиалга үүсэхгүй", "bug", "critical", "Backend API", "Цахим дэлгүүр", "Төлбөр", "qa_test"),
    ("Бүтээгдэхүүний зураг удаан ачаалж байна", "bug", "medium", "Вэб интерфэйс", "Цахим дэлгүүр", "Бүтээгдэхүүн", "in_progress"),
    ("Хүргэлтийн хаяг газрын зургаас сонгох", "cr", "medium", "Mobile апп", "Цахим дэлгүүр", "Хүргэлт", "new"),
    ("Хямдралын код ажиллахгүй байна", "bug", "high", "Backend API", "Цахим дэлгүүр", "Сагс", "assigned"),
    ("Бүтээгдэхүүний шүүлтүүрт үнийн муж нэмэх", "task", "low", "Вэб интерфэйс", "Цахим дэлгүүр", "Бүтээгдэхүүн", "closed"),
    ("Android апп нээгдэхдээ унаж байна", "bug", "critical", "Mobile апп", "Цахим дэлгүүр", "Сагс", "closed"),
    ("Захиалгын төлөвийн push мэдэгдэл", "cr", "medium", "Mobile апп", "Цахим дэлгүүр", "Хүргэлт", "resolved"),
    ("Бүтээгдэхүүний индекс нэмж хайлтыг хурдасгах", "task", "medium", "Өгөгдлийн сан", "Цахим дэлгүүр", "Бүтээгдэхүүн", "closed"),
    ("Админ хэсгийн эрхийн шалгалт дутуу", "bug", "high", "Аюулгүй байдал", "Цахим дэлгүүр", "Төлбөр", "in_progress"),
    ("Хүргэлтийн төлбөр буруу тооцогдож байна", "bug", "medium", "Backend API", "Цахим дэлгүүр", "Хүргэлт", "new"),
    ("Нүүр хуудасны баннер солих", "task", "low", "Вэб интерфэйс", "Цахим дэлгүүр", "Бүтээгдэхүүн", "new"),
]

COMMENTS = {
    "assigned": ["Хүлээж авлаа, өнөөдөр эхэлнэ.", "Логийг шалгаад хариу өгье."],
    "in_progress": ["Шалтгааныг олсон, засаж байна.", "Staging орчинд давтаж чадлаа."],
    "resolved": ["Засвар merge хийгдлээ, staging дээр шалгана уу.", "Unit тест нэмсэн."],
    "reopened": ["Зарим тохиолдолд дахин гарч байна — Safari дээр шалгаарай.", "Том файл дээр алдаа хэвээр."],
    "closed": ["Шалгалт амжилттай, хаалаа.", "Production дээр баталгаажлаа."],
    "rejected": ["Төхөөрөмжийн нийлүүлэгчийн талын асуудал тул манай хүрээнд биш."],
}

# Эцсийн төлөв хүртэлх замнал (workflow-ийн дагуу)
PATHS = {
    "new": [],
    "assigned": ["assigned"],
    "in_progress": ["assigned", "in_progress"],
    "resolved": ["assigned", "in_progress", "resolved"],
    "qa_test": ["assigned", "in_progress", "resolved", "qa_test"],
    "reopened": ["assigned", "in_progress", "resolved", "qa_test", "reopened"],
    "closed": ["assigned", "in_progress", "resolved", "qa_test", "closed"],
    "rejected": ["assigned", "in_progress", "rejected"],
}


class Command(BaseCommand):
    help = "Туршилт / танилцуулгад зориулсан demo өгөгдөл үүсгэнэ (давхардуулахгүй)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="Demo12345", help="Demo хэрэглэгчдийн нууц үг.")
        parser.add_argument("--tickets", action="store_true", help="Жишээ ticket-үүдийг мөн үүсгэнэ.")

    @transaction.atomic
    def handle(self, *args, password, tickets=False, **options):
        rng = random.Random(42)  # үр дүн давтагдахуйц
        users = self._users(password)
        teams = self._teams(users)
        categories = self._categories(teams)
        projects = self._projects()

        if not tickets:
            pass
        elif Ticket.objects.filter(reported_by__in=users.values()).exists():
            self.stdout.write(self.style.WARNING("Demo ticket-үүд аль хэдийн байна — алгаслаа."))
        else:
            count = self._tickets(rng, users, categories, projects)
            self.stdout.write(f"  {count} ticket үүсгэлээ")

        self.stdout.write(self.style.SUCCESS(
            f"Demo өгөгдөл бэлэн. Нэвтрэх: {', '.join(users)} — нууц үг: {password}"
        ))

    # ------------------------------------------------------------------ catalog

    def _users(self, password):
        users = {}
        for username, first, last, role in USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last, "email": f"{username}@demo.local"},
            )
            if created:
                user.set_password(password)
                user.save()
            user.groups.add(Group.objects.get_or_create(name=role)[0])
            users[username] = user
        return users

    def _teams(self, users):
        teams = {}
        for name, (lead, qa, members) in TEAMS.items():
            team, _ = Team.objects.get_or_create(
                name=name, defaults={"team_lead": users[lead], "qa_tester": users[qa]}
            )
            team.members.add(*(users[m] for m in members))
            teams[name] = team
        return teams

    def _categories(self, teams):
        categories = {}
        for name, (description, team_names) in CATEGORIES.items():
            category, _ = Category.objects.get_or_create(name=name, defaults={"description": description})
            for team_name in team_names:
                CategoryTeamAssignment.objects.get_or_create(category=category, team=teams[team_name])
            categories[name] = category
        return categories

    def _projects(self):
        projects = {}
        for name, (description, active, modules) in PROJECTS.items():
            project, _ = Project.objects.get_or_create(
                name=name, defaults={"description": description, "is_active": active}
            )
            for module in modules:
                Module.objects.get_or_create(project=project, name=module)
            projects[name] = project
        return projects

    # ------------------------------------------------------------------ tickets

    def _tickets(self, rng, users, categories, projects):
        now = timezone.now()
        reporters = [users[u] for u in ("bat.pm", "saraa.pm", "oyuka.qa", "munkh.qa", "anu", "nomin")]
        for title, ticket_type, priority, category_name, project_name, module_name, final in TICKETS:
            project = projects[project_name]
            ticket = Ticket.objects.create(
                title=title,
                description=self._description(ticket_type, title),
                ticket_type=ticket_type,
                priority=priority,
                category=categories[category_name],
                project=project,
                module=Module.objects.get(project=project, name=module_name),
                reported_by=rng.choice(reporters),
            )
            team = ticket.team
            path = PATHS[final]
            if path:
                ticket.assigned_to = rng.choice(list(team.members.all()))
            actors = {
                "assigned": team.team_lead, "in_progress": ticket.assigned_to,
                "resolved": ticket.assigned_to, "qa_test": ticket.assigned_to,
                "closed": team.qa_tester, "reopened": team.qa_tester, "rejected": ticket.assigned_to,
            }
            for status in path:
                ticket.transition_to(status, user=actors[status])
            self._backdate(rng, ticket, path, actors, now)
        return len(TICKETS)

    def _backdate(self, rng, ticket, path, actors, now):
        """Үүссэн огноо, төлөвийн түүх, SLA, сэтгэгдлийг сүүлийн 60 хоногт тааруулна."""
        open_ticket = not path or path[-1] not in ("closed", "rejected")
        resolution_h = settings.SLA_HOURS_BY_PRIORITY[ticket.priority]
        response_h = settings.SLA_FIRST_RESPONSE_HOURS_BY_PRIORITY[ticket.priority]
        if open_ticket:
            # Нээлттэй ticket-ийн ихэнх нь SLA хугацаандаа, цөөн нь хэтэрсэн байна.
            created = now - timedelta(hours=resolution_h * rng.uniform(0.2, 1.1) + 1)
        else:
            created = now - timedelta(days=rng.uniform(2, 58))
        # Ихэнх нь SLA-даа багтана, ~25% нь хэтэрнэ (dashboard-д бодит % гарна).
        stretch = rng.choice([0.3, 0.5, 0.6, 0.8, 1.4])

        moment = created
        stamps = []
        for index, status in enumerate(path):
            if index == 0:
                step = response_h * rng.uniform(0.2, 1.15)
            else:
                step = resolution_h * stretch / max(len(path), 1) * rng.uniform(0.6, 1.2)
            moment = min(moment + timedelta(hours=step), now - timedelta(minutes=5))
            stamps.append(moment)

        history = list(StatusHistory.objects.filter(ticket=ticket).order_by("id"))
        StatusHistory.objects.filter(pk=history[0].pk).update(changed_at=created)
        for row, stamp in zip(history[1:], stamps):
            StatusHistory.objects.filter(pk=row.pk).update(changed_at=stamp)

        for status, stamp in zip(path, stamps):
            texts = COMMENTS.get(status)
            if texts and rng.random() < 0.7:
                comment = Comment.objects.create(ticket=ticket, author=actors[status], body=rng.choice(texts))
                Comment.objects.filter(pk=comment.pk).update(created_at=stamp, updated_at=stamp)

        last = stamps[-1] if stamps else created
        sla_due = created + timedelta(hours=resolution_h)
        response_due = created + timedelta(hours=response_h)
        Ticket.objects.filter(pk=ticket.pk).update(
            created_at=created,
            updated_at=last,
            last_activity_at=last,
            sla_due_at=sla_due,
            first_response_due_at=response_due,
            first_responded_at=stamps[0] if stamps else None,
            # Өнгөрсөн хугацааны анхааруулгыг дахин мэйлээр илгээхгүйн тулд тэмдэглэнэ.
            sla_warning_sent_at=now if sla_due < now else None,
            sla_breach_notified_at=now if sla_due < now else None,
            first_response_warning_sent_at=now if response_due < now else None,
            first_response_breach_notified_at=now if response_due < now else None,
            stale_reminder_sent_at=now,
        )

    @staticmethod
    def _description(ticket_type, title):
        if ticket_type == "bug":
            return (
                f"{title}.\n\n"
                "Давтах алхам:\n1. Системд нэвтэрнэ\n2. Холбогдох хуудас руу орно\n3. Үйлдлийг гүйцэтгэнэ\n\n"
                "Хүлээгдэж буй үр дүн: алдаагүй ажиллах.\nБодит үр дүн: алдаа гарч байна.\n"
                "Орчин: Chrome 128, Windows 11 / Android 14"
            )
        if ticket_type == "cr":
            return f"{title}.\n\nХэрэглэгчдээс ирсэн санал. Бизнесийн үнэ цэнэ: хэрэглэгчийн сэтгэл ханамж нэмэгдэнэ."
        return f"{title}.\n\nХийх ажил, хүлээн авах шалгуурыг ажлын явцад тодруулна."
