"""
Тест зөвхөн бүртгэлтэй орчны хаяг руу хандана. Үүнээс гадна:
  * cloud metadata (169.254.x.x) зэрэг link-local хаягийг үргэлж хаана;
  * localhost / дотоод сүлжээг (10.x, 192.168.x ...) AUTOTEST_ALLOW_PRIVATE_HOSTS=True
    үед л зөвшөөрнө (жишээ нь QA дотоод сүлжээний staging шалгадаг бол).
"""
import ipaddress
import socket
from urllib.parse import urlsplit

from django.conf import settings
from django.utils.translation import gettext as _


class UnsafeURL(ValueError):
    pass


def check_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURL(_("Зөвхөн http:// эсвэл https:// хаяг зөвшөөрөгдөнө."))
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeURL(_("'%(host)s' хаягийг олсонгүй (DNS).") % {"host": parts.hostname})

    allow_private = getattr(settings, "AUTOTEST_ALLOW_PRIVATE_HOSTS", False)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise UnsafeURL(_("Энэ хаяг руу тест илгээх боломжгүй."))
        if (ip.is_loopback or ip.is_private) and not allow_private:
            raise UnsafeURL(
                _("Дотоод сүлжээний хаяг (%(ip)s) руу тест илгээхийг зөвшөөрөөгүй байна. "
                  "Админ AUTOTEST_ALLOW_PRIVATE_HOSTS тохиргоог асааж болно.") % {"ip": ip}
            )
