from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.tickets.models import StatusHistory, Ticket
from apps.tickets.permissions import ROLE_DEV, ROLE_PM
from apps.tickets.reports import (
    _compliance_level,
    _compliance_percent,
    _nice_axis,
    build_report,
    clean_period,
)

from .helpers import make_project, make_routed_category, make_user


class CleanPeriodTests(TestCase):
    def test_allowed_values_pass_through(self):
        self.assertEqual(clean_period("7"), 7)
        self.assertEqual(clean_period("30"), 30)
        self.assertEqual(clean_period("90"), 90)

    def test_invalid_or_missing_defaults_to_30(self):
        self.assertEqual(clean_period(None), 30)
        self.assertEqual(clean_period(""), 30)
        self.assertEqual(clean_period("bogus"), 30)
        self.assertEqual(clean_period("14"), 30)


class ComplianceHelpersTests(TestCase):
    def test_percent_none_when_no_data(self):
        self.assertIsNone(_compliance_percent(0, 0))

    def test_percent_rounds_to_one_decimal(self):
        self.assertEqual(_compliance_percent(2, 1), 66.7)

    def test_level_thresholds(self):
        self.assertEqual(_compliance_level(None), "none")
        self.assertEqual(_compliance_level(95), "good")
        self.assertEqual(_compliance_level(90), "good")
        self.assertEqual(_compliance_level(80), "warning")
        self.assertEqual(_compliance_level(70), "warning")
        self.assertEqual(_compliance_level(50), "critical")


class NiceAxisTests(TestCase):
    def test_zero_returns_default_ticks(self):
        self.assertEqual(_nice_axis(0), (4, 1))

    def test_small_value_never_zero_step(self):
        y_max, step = _nice_axis(1)
        self.assertGreaterEqual(step, 1)
        self.assertGreaterEqual(y_max, 1)

    def test_max_at_least_covers_value(self):
        y_max, _step = _nice_axis(37)
        self.assertGreaterEqual(y_max, 37)


class BuildReportTests(TestCase):
    def setUp(self):
        self.reporter = make_user("reporter")
        self.dev1 = make_user("dev1")
        self.dev2 = make_user("dev2")
        self.category, self.team = make_routed_category()
        self.project = make_project()
        self.now = timezone.now()

    def _ticket(self, days_ago, status, priority=Ticket.Priority.MEDIUM, assigned_to=None):
        t = Ticket.objects.create(
            title=f"T-{days_ago}-{status}",
            description="d",
            ticket_type=Ticket.TicketType.BUG,
            category=self.category,
            project=self.project,
            reported_by=self.reporter,
            priority=priority,
            assigned_to=assigned_to,
        )
        Ticket.objects.filter(pk=t.pk).update(
            created_at=self.now - timedelta(days=days_ago), status=status
        )
        t.refresh_from_db()
        return t

    def test_created_and_open_counts(self):
        self._ticket(2, Ticket.Status.NEW)
        self._ticket(2, Ticket.Status.ASSIGNED, assigned_to=self.dev1)
        self._ticket(2, Ticket.Status.CLOSED)
        self._ticket(2, Ticket.Status.REJECTED)

        report = build_report(days=30)
        self.assertEqual(report["created_count"], 4)
        # open_count-д CLOSED/REJECTED тооцогдохгүй.
        self.assertEqual(report["open_count"], 2)

    def test_tickets_outside_period_excluded(self):
        self._ticket(2, Ticket.Status.NEW)
        self._ticket(40, Ticket.Status.NEW)

        report = build_report(days=30)
        self.assertEqual(report["created_count"], 1)

    def test_first_response_met_vs_breached(self):
        met_ticket = self._ticket(2, Ticket.Status.ASSIGNED, assigned_to=self.dev1)
        Ticket.objects.filter(pk=met_ticket.pk).update(
            first_response_due_at=self.now - timedelta(days=1, hours=12),
            first_responded_at=self.now - timedelta(days=1, hours=20),
        )

        breached_ticket = self._ticket(2, Ticket.Status.ASSIGNED, assigned_to=self.dev1)
        Ticket.objects.filter(pk=breached_ticket.pk).update(
            first_response_due_at=self.now - timedelta(days=1, hours=12),
            first_responded_at=self.now - timedelta(days=1, hours=6),
        )

        pending_ticket = self._ticket(0, Ticket.Status.NEW)
        Ticket.objects.filter(pk=pending_ticket.pk).update(
            first_response_due_at=self.now + timedelta(hours=5),
        )

        report = build_report(days=30)
        stats = report["first_response"]
        self.assertEqual(stats["met"], 1)
        self.assertEqual(stats["breached"], 1)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["percent"], 50.0)
        self.assertEqual(stats["level"], "critical")

    def test_resolution_met_and_rejected_excluded(self):
        closed = self._ticket(3, Ticket.Status.CLOSED)
        Ticket.objects.filter(pk=closed.pk).update(sla_due_at=self.now + timedelta(days=1))
        StatusHistory.objects.create(
            ticket=closed,
            from_status="qa_test",
            to_status=Ticket.Status.CLOSED,
            changed_by=None,
        )
        # StatusHistory.changed_at нь auto_now_add тул шууд update хийж
        # "хугацаандаа хаасан" гэдгийг баталгаажуулна.
        StatusHistory.objects.filter(ticket=closed, to_status=Ticket.Status.CLOSED).update(
            changed_at=self.now - timedelta(hours=1)
        )

        rejected = self._ticket(3, Ticket.Status.REJECTED)
        Ticket.objects.filter(pk=rejected.pk).update(sla_due_at=self.now - timedelta(hours=1))

        report = build_report(days=30)
        stats = report["resolution"]
        self.assertEqual(stats["met"], 1)
        self.assertEqual(stats["breached"], 0)

    def test_agent_breakdown_groups_by_assignee(self):
        self._ticket(2, Ticket.Status.ASSIGNED, assigned_to=self.dev1)
        self._ticket(2, Ticket.Status.IN_PROGRESS, assigned_to=self.dev1)
        closed = self._ticket(2, Ticket.Status.CLOSED, assigned_to=self.dev2)
        StatusHistory.objects.create(
            ticket=closed, from_status="qa_test", to_status=Ticket.Status.CLOSED
        )

        report = build_report(days=30)
        by_user = {row["user"].username: row for row in report["agents"]}
        self.assertEqual(by_user["dev1"]["assigned"], 2)
        self.assertEqual(by_user["dev1"]["active"], 2)
        self.assertEqual(by_user["dev2"]["closed"], 1)
        self.assertIsNotNone(by_user["dev2"]["avg_resolution_hours"])

    def test_unassigned_tickets_excluded_from_agent_rows(self):
        self._ticket(2, Ticket.Status.NEW)
        report = build_report(days=30)
        self.assertEqual(report["agents"], [])

    def test_priority_breakdown_percentages(self):
        self._ticket(1, Ticket.Status.NEW, priority=Ticket.Priority.HIGH)
        self._ticket(1, Ticket.Status.NEW, priority=Ticket.Priority.HIGH)
        self._ticket(1, Ticket.Status.NEW, priority=Ticket.Priority.LOW)

        report = build_report(days=30)
        rows = {row["key"]: row for row in report["by_priority"]}
        self.assertEqual(rows["high"]["count"], 2)
        self.assertAlmostEqual(rows["high"]["percent"], 66.7, places=1)
        self.assertEqual(rows["low"]["count"], 1)

    def test_trend_covers_full_period_inclusive(self):
        report = build_report(days=7)
        self.assertEqual(len(report["trend"]), 8)  # since..now inclusive

    def test_chart_has_no_zero_division_when_empty(self):
        report = build_report(days=7)
        self.assertFalse(report["chart"]["has_data"])
        for series in report["chart"]["series"]:
            self.assertEqual(series["total"], 0)


class ReportsViewTests(TestCase):
    def setUp(self):
        self.pm = make_user("pm", ROLE_PM)
        self.dev = make_user("dev", ROLE_DEV)
        self.category, self.team = make_routed_category()
        self.project = make_project()

    def test_pm_can_access(self):
        self.client.force_login(self.pm)
        response = self.client.get(reverse("tickets:reports"))
        self.assertEqual(response.status_code, 200)

    def test_developer_redirected(self):
        self.client.force_login(self.dev)
        response = self.client.get(reverse("tickets:reports"))
        self.assertEqual(response.status_code, 302)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("tickets:reports"))
        self.assertEqual(response.status_code, 302)

    def test_default_period_is_30_days(self):
        self.client.force_login(self.pm)
        response = self.client.get(reverse("tickets:reports"))
        self.assertEqual(response.context["days"], 30)

    def test_each_allowed_period_renders(self):
        self.client.force_login(self.pm)
        for days in (7, 30, 90):
            response = self.client.get(reverse("tickets:reports"), {"days": days})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["days"], days)

    def test_empty_dataset_renders_without_error(self):
        self.client.force_login(self.pm)
        response = self.client.get(reverse("tickets:reports"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ticket алга байна")
