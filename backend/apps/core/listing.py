"""
Удирдлагын жагсаалтуудын (Хэрэглэгч, Төсөл, Ангилал, Баг) хайлт / шүүлтүүр /
эрэмбэ / хуудаслалт — бүгд GET параметрээр, сервер талд хийгдэнэ.

View бүр `ListConfig` зарлаад `build_listing(request, queryset, config)`-г дуудна;
template нь `_list_toolbar.html`, `_pagination.html`-ийг include хийнэ.
"""
from dataclasses import dataclass, field
from functools import reduce
from operator import or_

from django.core.paginator import Paginator
from django.db.models import Q

LIST_PAGE_SIZE = 25


@dataclass
class ListFilter:
    """Нэг dropdown шүүлтүүр. `choices` — [(value, label)], `apply(qs, value)` → qs."""

    name: str
    label: str
    choices: list
    apply: object


@dataclass
class ListConfig:
    search_fields: list
    search_placeholder: str
    # key → (label, order_by tuple)
    sorts: dict
    default_sort: str
    filters: list = field(default_factory=list)


def build_listing(request, queryset, config, page_size=LIST_PAGE_SIZE):
    params = request.GET
    q = params.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            reduce(or_, (Q(**{f"{name}__icontains": q}) for name in config.search_fields))
        )

    filters = []
    for list_filter in config.filters:
        value = params.get(list_filter.name, "")
        valid = {str(v) for v, _label in list_filter.choices}
        if value and value in valid:
            queryset = list_filter.apply(queryset, value)
        else:
            value = ""
        filters.append({"name": list_filter.name, "label": list_filter.label,
                        "choices": [(str(v), l) for v, l in list_filter.choices], "value": value})

    sort = params.get("sort", "")
    if sort not in config.sorts:
        sort = config.default_sort
    queryset = queryset.order_by(*config.sorts[sort][1]).distinct()

    page_obj = Paginator(queryset, page_size).get_page(params.get("page"))
    querystring = params.copy()
    querystring.pop("page", None)

    return {
        "page_obj": page_obj,
        "object_list": page_obj.object_list,
        "list_q": q,
        "list_filters": filters,
        "list_sort": sort,
        "list_sorts": [(key, label) for key, (label, _order) in config.sorts.items()],
        "list_search_placeholder": config.search_placeholder,
        "list_is_filtered": bool(q or any(f["value"] for f in filters)),
        "querystring": querystring.urlencode(),
    }
