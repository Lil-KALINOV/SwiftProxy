import random
import time
from collections import Counter

from typing import Dict, List, Iterator


_DOMAIN_FAIL_COOLDOWN = 300.0


class _Balancer:
    def __init__(self):
        self.domains: List[str] = []
        self._dc_to_domain: Dict[int, str] = {}
        self._domain_failures: Dict[str, int] = {}
        self._domain_last_fail: Dict[str, float] = {}

    def update_domains_list(self, domains_list: List[str]) -> None:
        if Counter(self.domains) == Counter(domains_list):
            return

        self.domains = domains_list[:]

        self._dc_to_domain = {
            dc_id: random.choice(self.domains)
            for dc_id in (1, 2, 3, 4, 5, 203)
        }

    def update_domain_for_dc(self, dc_id: int, domain: str) -> bool:
        if self._dc_to_domain.get(dc_id) == domain:
            return False

        self._dc_to_domain[dc_id] = domain
        self.report_domain_success(domain)
        return True

    def report_domain_failure(self, domain: str) -> None:
        self._domain_last_fail[domain] = time.monotonic()
        self._domain_failures[domain] = self._domain_failures.get(domain, 0) + 1

    def report_domain_success(self, domain: str) -> None:
        self._domain_failures.pop(domain, None)
        self._domain_last_fail.pop(domain, None)

    def _get_healthy_domains(self) -> List[str]:
        now = time.monotonic()
        healthy = []
        for domain in self.domains:
            failures = self._domain_failures.get(domain, 0)
            if failures == 0:
                healthy.append(domain)
                continue
            last_fail = self._domain_last_fail.get(domain, 0)
            if now - last_fail > _DOMAIN_FAIL_COOLDOWN:
                self._domain_failures.pop(domain, None)
                self._domain_last_fail.pop(domain, None)
                healthy.append(domain)
        return healthy or self.domains[:1]

    def get_domains_for_dc(self, dc_id: int) -> Iterator[str]:
        healthy = self._get_healthy_domains()
        current_domain = self._dc_to_domain.get(dc_id)

        if current_domain in healthy:
            yield current_domain

        for domain in healthy:
            if domain != current_domain:
                yield domain

        for domain in self.domains:
            if domain != current_domain and domain not in healthy:
                yield domain


balancer = _Balancer()
