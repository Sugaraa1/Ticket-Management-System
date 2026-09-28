# Foxt TMS — Дүрэм ба тестийн хүснэгт (Requirements Traceability Matrix)

Системийн дүрэм бүр ID-тай бөгөөд түүнийг шалгадаг тесттэй холбогдоно. Тестийн docstring нь
`[ID]`-аар эхэлдэг тул `manage.py test`-ийн лог дээр аль дүрэм давсан/унасан нь шууд харагдана.

**Эх сурвалж (стандарт):**
- **NIST SP 800-63B** — нууц үгийн бодлого
- **OWASP ASVS 4.0** — нэвтрэлт (V2), session (V3), оролт/гаралт (V5), CSRF ба HTTP header (V13/V14)
- **OWASP File Upload Cheat Sheet** — файл хавсаргах
- **ITIL 4** (Incident / Service Request management) — тикетийн бүртгэл, workflow, аудит
- **Least privilege** — эрх бүр зөвхөн хэрэгтэй хүнд

**Төлөв:** ✅ тест давсан · ❌ тест унасан (дүрэм кодонд хэрэгжээгүй — засах шаардлагатай)

Ажиллуулах: `DATABASE_URL=sqlite:///:memory: .venv/bin/python manage.py test`

---

## AUTH — Нууц үг ба нэвтрэлт (NIST 800-63B, ASVS V2)

| ID | Дүрэм | Эх сурвалж | Тест | Төлөв |
|---|---|---|---|---|
| AUTH-01 | Нууц үг дор хаяж 8 тэмдэгт | NIST §5.1.1.2 | `accounts/test_rules_auth.py` → `test_short_password_rejected`, `test_eight_characters_accepted` | ✅ |
| AUTH-02 | Түгээмэл нууц үгийг хориглоно | NIST §5.1.1.2 | `test_common_password_rejected` | ✅ |
| AUTH-03 | Зөвхөн тооноос бүрдсэн нууц үгийг хориглоно | NIST §5.1.1.2 | `test_numeric_only_rejected` | ✅ |
| AUTH-04 | Хэрэглэгчийн нэртэй төстэй нууц үгийг хориглоно | NIST §5.1.1.2 | `test_similar_to_username_rejected` | ✅ |
| AUTH-05 | 64 тэмдэгт хүртэлх урт нууц үгийг зөвшөөрнө | NIST §5.1.1.2 | `test_long_passphrase_accepted` | ✅ |
| AUTH-06 | Тэмдэгт/том үсэг заавал шаардахгүй (найрлагын дүрэмгүй) | NIST §5.1.1.2 | `test_no_forced_composition_rules` | ✅ |
| AUTH-07 | Нууц үгийн алдааны мессеж монгол хэл дээр | UX / i18n | `test_error_messages_are_in_mongolian` | ✅ |
| AUTH-08 | 5 удаа буруу оролдсоны дараа нэвтрэлтийг түр хаана | ASVS 2.2.1 | `test_repeated_failed_logins_are_throttled` | ✅ |
| AUTH-09 | Нэвтэрсний дараа гадны сайт руу шилжүүлэхгүй (open redirect) | ASVS 5.1.5 | `test_external_next_redirect_is_ignored` | ✅ |
| AUTH-10 | Гарсны дараа session дуусна | ASVS 3.3.1 | `test_logout_ends_session` | ✅ |
| AUTH-11 | Идэвхгүй хэрэглэгч нэвтэрч чадахгүй | ASVS 2.1 | `accounts/tests.py` → `test_deactivate_button_blocks_login_but_keeps_user` | ✅ |
| AUTH-12 | Нууц үг сэргээхэд и-мэйл бүртгэлтэй эсэхийг ил гаргахгүй | ASVS 2.5.x | `test_unknown_email_does_not_reveal_anything`, `test_full_reset_flow`, `test_invalid_link_shows_message` | ✅ |

> **Анхаар (AUTH-06):** NIST стандарт "заавал тэмдэгт/том үсэг агуулна" гэсэн дүрмийг
> **хэрэглэхгүй байхыг** зөвлөдөг — хэрэглэгчид `Password1!` мэт таамаглахад хялбар загвар руу
> түлхдэг. Оронд нь урт + түгээмэл нууц үгийн жагсаалтаар шалгах нь илүү аюулгүй.

## SEC — Аюулгүй байдлын суурь (ASVS V5, V13, V14)

| ID | Дүрэм | Эх сурвалж | Тест | Төлөв |
|---|---|---|---|---|
| SEC-01 | CSRF токенгүй POST-ыг татгалзана | ASVS 13.2.3 | `test_post_without_csrf_token_is_rejected` | ✅ |
| SEC-02 | `X-Content-Type-Options: nosniff` | ASVS 14.4.4 | `test_nosniff_header` | ✅ |
| SEC-03 | `X-Frame-Options: DENY` (clickjacking) | ASVS 14.4.7 | `test_clickjacking_header` | ✅ |
| SEC-04 | Хэрэглэгчийн оруулсан текст (гарчиг, тайлбар, comment) HTML болж ажиллахгүй | ASVS 5.3.3 | `tickets/tests/test_rules_tickets.py` → `test_ticket_title_is_escaped_everywhere`; `test_mentions.py` → `test_comment_is_escaped` | ✅ |
| SEC-05 | Бүх дотоод хуудас нэвтрэлт шаардана | ASVS 4.1 | `test_every_page_requires_login` | ✅ |
| SEC-06 | CSV/Excel экспортод formula injection-оос хамгаална | OWASP CSV Injection | `test_review_fixes.py` → `test_formula_injection_is_neutralised` | ✅ |
| SEC-07 | Гадны `next` URL-ыг бөөн үйлдлийн дараа дагахгүй | ASVS 5.1.5 | `test_bulk_actions.py` → `test_external_next_url_is_ignored` | ✅ |

## ATT — Файл хавсаргах (OWASP File Upload Cheat Sheet)

| ID | Дүрэм | Тест (`tickets/tests/test_attachment_rules.py`) | Төлөв |
|---|---|---|---|
| ATT-01 | Зөвхөн зөвшөөрөгдсөн өргөтгөл (зураг, баримт, zip); том/жижиг үсэг ялгахгүй | `test_images_are_accepted`, `test_documents_are_accepted`, `test_extension_is_case_insensitive` | ✅ |
| ATT-02 | Ажиллах файл, скрипт, html, svg-г хориглоно | `test_executables_and_scripts_are_rejected`, `test_html_and_svg_are_rejected` | ✅ |
| ATT-03 | Давхар өргөтгөл (`a.png.exe`) болон өргөтгөлгүй файлыг хориглоно | `test_double_extension_is_judged_by_last_one`, `test_file_without_extension_is_rejected` | ✅ |
| ATT-04 | Файлын **агуулга** өргөтгөлтэйгөө таарна (magic bytes) | `test_file_content_must_match_extension` | ✅ |
| ATT-05 | Хэмжээний хязгаар (яг хязгаар ✅, +1 байт ❌) | `test_file_at_limit_is_accepted`, `test_file_over_limit_is_rejected` | ✅ |
| ATT-06 | Хуудсаар илгээхэд ч дүрэм мөрдөгдөнө; хэн хавсаргасныг бүртгэнэ | `test_allowed_file_is_saved_to_ticket`, `test_forbidden_file_is_not_saved` | ✅ |
| ATT-07 | Хавсаргах/татахад нэвтрэлт шаардана; файл нийтийн `media/`-д биш | `test_anonymous_user_cannot_upload`; `test_access_rules.py` → `test_attachment_requires_login_and_is_not_under_media` | ✅ |
| ATT-08 | Файлын нэрээр (`../../`) хадгалах хавтаснаас гарахгүй | `test_malicious_filename_stays_inside_storage` | ✅ |
| ATT-09 | Зураг/PDF хөтөчид нээгдэнэ, бусад нь зөвхөн татагдана | `test_download_disposition_by_type` | ✅ |

## TKT — Тикетийн өгөгдөл (ITIL: бүртгэлийн бүрэн байдал)

| ID | Дүрэм | Тест | Төлөв |
|---|---|---|---|
| TKT-01 | Гарчиг, төрөл, ангилал, төсөл, тайлбар заавал | `test_rules_tickets.py` → `test_required_fields` | ✅ |
| TKT-02 | Хоосон зайнаас бүрдсэн гарчгийг хүлээж авахгүй | `test_whitespace_only_title_rejected` | ✅ |
| TKT-03 | Гарчиг ≤ 255 тэмдэгт | `test_title_length_limit` | ✅ |
| TKT-04 | Чухлын зэрэг зөвхөн жагсаалтаас | `test_unknown_priority_rejected` | ✅ |
| TKT-05 | Шинэ тикет: "Шинэ" төлөв, хариуцагчгүй, SLA хугацаатай | `test_new_ticket_starts_as_new_and_unassigned` | ✅ |
| TKT-06 | Мэдээлэгчийг хуурамчаар өөрчлөх боломжгүй | `test_reporter_cannot_be_forged` | ✅ |
| TKT-07 | Модуль сонгосон төсөлдөө харьяалагдана | `test_forms.py` (3 тест), `test_ticket_edit.py` → `test_module_must_belong_to_project` | ✅ |
| TKT-08 | Дэд ангилал сонгосон ангилалдаа харьяалагдана | `categories/tests.py` → `SubcategoryTests` | ✅ |
| TKT-09 | Идэвхгүй төсөлд шинэ тикет үүсгэхгүй | `accounts/tests.py` → `test_inactive_project_hidden_from_ticket_form` | ✅ |
| TKT-10 | Ангилал автоматаар багт чиглүүлнэ (ачаалал багатай руу) | `test_models.py` → `test_ticket_gets_team_from_category_assignment`; `categories/tests.py` → `test_ticket_routes_to_least_loaded_team` | ✅ |
| TKT-11 | Засвар бүр түүхэнд бүртгэгдэнэ; хаагдсан тикетийг засахгүй | `test_ticket_edit.py` → `test_reporter_edits_and_change_is_logged`, `test_pm_can_edit_but_not_closed_ticket` | ✅ |
| TKT-12 | Оноогдсоны дараа ангиллыг солихгүй | `test_ticket_edit.py` → `test_category_locked_after_assignment` | ✅ |

## WF — Workflow (ITIL Incident lifecycle)

| ID | Дүрэм | Тест | Төлөв |
|---|---|---|---|
| WF-01 | Төлөв шилжих бүрт хэн/хэзээ/хаанаас хаашаа гэдгийг бүртгэнэ (аудит) | `test_rules_tickets.py` → `test_transition_is_audited_with_actor`; `test_models.py` → `test_creates_status_history_on_create` | ✅ |
| WF-02 | Татгалзахдаа шалтгаан заавал бичнэ | `test_rejection_requires_reason`, `test_rejection_with_reason_succeeds` | ✅ |
| WF-03 | QA буцаахдаа (дахин нээх) шалтгаан заавал бичнэ | `test_qa_reopen_requires_reason` | ✅ |
| WF-04 | Татгалзсан тикетийг зөвхөн PM/Admin дахин нээнэ | `test_developer_cannot_reopen_rejected_ticket` | ✅ |
| WF-05 | Хаагдсан тикет эцсийн төлөв | `test_closed_ticket_is_final` | ✅ |
| WF-06 | QA-г алгасаж хаах боломжгүй | `test_reporter_cannot_close_own_ticket_bypassing_qa`; `test_review_fixes.py` → `test_other_team_qa_cannot_close` | ✅ |
| WF-07 | Зөвшөөрөгдсөн шилжилтүүд л хийгдэнэ | `test_models.py` → `test_allowed_transitions`, `test_disallowed_transitions` | ✅ |
| WF-08 | Developer-ийн алхмуудыг зөвхөн хариуцагч хийнэ | `test_permissions.py` → `test_assignee_only_transition_*`; `test_review_fixes.py` → `test_other_developer_cannot_*` | ✅ |
| WF-09 | Хариуцагч багийнхаа идэвхтэй гишүүн рүү л шилжүүлнэ; Team Lead-д мэдэгдэнэ | `test_review_fixes.py` → `test_assignee_can_hand_over_to_teammate`, `test_assignee_cannot_hand_over_to_outsider`, `test_hand_over_notifies_team_lead` | ✅ |

## PERM — Эрх (least privilege)

| ID | Дүрэм | Тест | Төлөв |
|---|---|---|---|
| PERM-01 | Хэрэглэгч удирдлага зөвхөн Admin | `accounts/tests.py` → `test_non_admin_cannot_access`, `test_non_admin_cannot_edit` | ✅ |
| PERM-02 | Admin өөрийгөө идэвхгүй болгох / Admin эрхээ хасахгүй | `test_cannot_deactivate_self`, `test_admin_cannot_drop_own_admin_role` | ✅ |
| PERM-03 | Ангилал, төсөл, багийн удирдлага зөвхөн PM/Admin; ангилал устгах зөвхөн Admin | `categories/tests.py` → `test_pm_cannot_delete`, `test_developer_cannot_add_subcategory`; `projects/tests.py` → `test_developer_cannot_*` | ✅ |
| PERM-04 | Team Lead-ийн эрх зөвхөн өөрийн багт | `test_access_rules.py` → `test_team_lead_rights_do_not_leak_to_other_teams` | ✅ |
| PERM-05 | Дотоод тэмдэглэлийг зөвхөн баг/PM харна | `test_internal_note_hidden_from_reporter_outside_team`, `test_outsider_cannot_post_internal_note` | ✅ |
| PERM-06 | Бөөн үйлдэл, чухлын зэрэг өөрчлөх зөвхөн PM/Admin/Team Lead | `test_bulk_actions.py`, `test_priority_and_profile.py` → `test_developer_cannot_change_priority_via_view` | ✅ |
| PERM-07 | Нийт тайлан/экспорт PM/Admin; Team Lead зөвхөн өөрийн баг | `test_exports.py` (10 тест) | ✅ |
| PERM-08 | Түүхтэй хэрэглэгч/төсөл/ангиллыг устгахгүй (идэвхгүй болгоно) | `test_user_with_tickets_is_deactivated_not_deleted`, `test_project_with_tickets_is_deactivated_not_deleted`, `test_category_with_tickets_is_kept` | ✅ |

## SLA ба мэдэгдэл

| ID | Дүрэм | Тест | Төлөв |
|---|---|---|---|
| SLA-01 | Чухлын зэргээс SLA хугацаа тооцогдоно; зэрэг солиход дахин тооцно | `test_models.py` → `test_sla_due_at_set_from_priority`; `test_change_priority_recalculates_sla_from_creation` | ✅ |
| SLA-02 | Анхны хариу / шийдвэрлэлтийн хугацаа хэтрэхэд анхааруулга, escalation (давтахгүй) | `test_sla_escalation.py` (14 тест) | ✅ |
| SLA-03 | Идэвхгүй тикетэд сануулга; хаагдсаныг алгасна | `test_stale_ticket_automation.py` (10 тест) | ✅ |
| NOTIF-01 | Төлөв бүрт дараагийн алхмыг хийх хүнд л мэйл; үйлдэл хийсэн хүнд илгээхгүй | `test_notifications.py` (13 тест) | ✅ |
| NOTIF-02 | @mention нэг удаа; дотоод тэмдэглэлийг харах эрхгүй хүнд илгээхгүй | `test_mentions.py` | ✅ |
| NOTIF-03 | Мэйл илгээх алдаа системийг унагахгүй, логлогдоно | `test_send_failure_is_logged_not_raised` | ✅ |

---

## Хураангуй

| Хэсэг | Дүрэм | ✅ | ❌ |
|---|---|---|---|
| AUTH | 12 | 12 | 0 |
| SEC | 7 | 7 | 0 |
| ATT | 9 | 9 | 0 |
| TKT | 12 | 12 | 0 |
| WF | 9 | 9 | 0 |
| PERM | 8 | 8 | 0 |
| SLA / NOTIF | 6 | 6 | 0 |
| **Нийт** | **63** | **63** | **0** |

Шинэ дүрэм нэмэхдээ: энэ хүснэгтэд ID-тай мөр нэмж, docstring нь `"""[ID] ..."""` гэж эхэлсэн тест бичнэ.
