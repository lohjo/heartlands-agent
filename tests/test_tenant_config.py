"""Progressive trust: an incomplete tenant_config must degrade gracefully
(success criterion #4 / ADR-7) — fallback language, never errors."""

from shared.tenant_config import (
    default_config, field_or_fallback, remember_fact, load_tenant_config,
)


def test_new_merchant_starts_at_stage_one_with_blanks():
    cfg = default_config('t_new')
    assert cfg['onboarding_stage'] == 1
    assert cfg['merchant_name'] is None
    assert cfg['suppliers'] == {}


def test_missing_field_returns_fallback_not_error():
    cfg = default_config('t1')
    # Unknown supplier → caller-supplied fallback, never a crash or a guess.
    assert field_or_fallback(cfg, 'rice_supplier', 'unknown') == 'unknown'
    assert field_or_fallback(cfg, 'shop_name') is None


def test_remember_fact_grows_config_progressively():
    remember_fact('t_grow', 'shop_name', 'Lim Provision')
    remember_fact('t_grow', 'rice_supplier', 'Lim Huat')
    cfg = load_tenant_config('t_grow')
    assert cfg['shop_name'] == 'Lim Provision'
    assert field_or_fallback(cfg, 'rice_supplier') == 'Lim Huat'


def test_free_form_fact_lands_in_facts_bucket():
    cfg = remember_fact('t_facts', 'opening_hours', '7am-9pm')
    assert cfg['facts']['opening_hours'] == '7am-9pm'
    assert field_or_fallback(cfg, 'opening_hours') == '7am-9pm'
