"""Unit tests for cyber.resilience_logic and cyber.tls — no database."""
import datetime as dt
import socket
import ssl
import threading
from datetime import date, datetime, timedelta

import pytest

from cyber import resilience_logic as logic
from cyber import tls

T = date(2026, 10, 1)
NOW = datetime(2026, 10, 1, 12, 0)


class TestDR:
    sites = [{'site_type': 'dr', 'is_active': True}]

    def test_no_site(self):
        assert logic.dr_issues([{'site_type': 'primary'}], [], T, 12) == ['no active DR / backup site registered']

    def test_never_tested(self):
        assert logic.dr_issues(self.sites, [], T, 12) == ['DR site never tested']

    def test_old_and_partial(self):
        out = logic.dr_issues(self.sites, [{'test_date': date(2025, 8, 1), 'result': 'partial'}], T, 12)
        assert len(out) == 2

    def test_ok(self):
        assert logic.dr_issues(self.sites, [{'test_date': date(2026, 5, 1), 'result': 'pass'}], T, 12) == []


class TestBackups:
    def test_issues(self):
        b = {'location_type': 'onsite', 'encrypted': False, 'last_success_at': NOW - timedelta(days=10), 'last_status': 'failed'}
        assert len(logic.backup_issues(b, NOW, 7)) == 4

    def test_ok(self):
        b = {'location_type': 'offsite', 'encrypted': True, 'last_success_at': NOW - timedelta(hours=5), 'last_status': 'success'}
        assert logic.backup_issues(b, NOW, 7) == []


class TestIntegrationsAssessments:
    def test_integration(self):
        assert logic.integration_issue({'status': 'not_connected'}, NOW) == 'status: not_connected'
        assert 'older' in logic.integration_issue({'status': 'live', 'last_success_at': NOW - timedelta(hours=30)}, NOW, 24)
        assert logic.integration_issue({'status': 'live', 'last_success_at': NOW - timedelta(hours=2)}, NOW, 24) is None

    def test_assessment(self):
        a = {'status': 'accepted', 'performed_on': date(2026, 1, 1), 'valid_until': date(2027, 1, 1), 'critical_open': 0}
        assert logic.assessment_issue([a], T) is None
        assert 'expired' in logic.assessment_issue([dict(a, valid_until=date(2026, 6, 1))], T)
        assert 'critical' in logic.assessment_issue([dict(a, critical_open=2)], T, 0)
        assert logic.assessment_issue([dict(a, critical_open=2)], T, None) is None
        assert logic.assessment_issue([dict(a, status='draft')], T) == 'no accepted assessment'


class TestAssetsCerts:
    def test_asset_state(self):
        assert logic.asset_state({'licence_expiry': date(2026, 9, 1)}, T) == 'expired'
        assert logic.asset_state({'licence_expiry': date(2026, 10, 15)}, T, 30) == 'expiring'
        assert logic.asset_state({'licence_expiry': date(2027, 10, 15)}, T, 30) == 'ok'
        assert logic.asset_state({}, T) == 'no_licence'

    def test_residency(self):
        assert logic.residency_issue({}) == 'data-residency not attested'
        assert 'abroad' in logic.residency_issue({'sends_data_abroad': True, 'residency_attested_on': T})
        assert logic.residency_issue({'sends_data_abroad': False, 'residency_attested_on': T}) is None

    def test_cert_state(self):
        base = {'last_checked_at': NOW - timedelta(hours=1), 'cert_not_after': NOW + timedelta(days=100)}
        assert logic.cert_state(base, NOW, 30) == 'ok'
        assert logic.cert_state(dict(base, cert_not_after=NOW + timedelta(days=10)), NOW, 30) == 'expiring'
        assert logic.cert_state(dict(base, cert_not_after=NOW - timedelta(days=1)), NOW, 30) == 'expired'
        assert logic.cert_state(dict(base, last_error='x'), NOW, 30) == 'error'
        assert logic.cert_state({}, NOW) == 'unchecked'
        assert logic.cert_state(dict(base, last_checked_at=NOW - timedelta(days=5)), NOW, 30) == 'stale'


class TestMaturityRisks:
    def test_summary(self):
        s = logic.maturity_summary([{'current_level': 2, 'target_level': 3}, {'current_level': 4, 'target_level': 3},
                                    {'current_level': None, 'target_level': 3}])
        assert s['avg_current'] == 3.0 and len(s['gaps']) == 1 and s['unrated'] == 1

    def test_risk_stale(self):
        assert 'overdue' in logic.risk_stale({'status': 'ACTIVE', 'next_review_date': date(2026, 9, 1)}, T, 180)
        assert logic.risk_stale({'status': 'ACTIVE', 'last_review_date': date(2026, 8, 1)}, T, 180) is None
        assert logic.risk_stale({'status': 'ACTIVE'}, T, 180) == 'never reviewed'
        assert logic.risk_stale({'status': 'CLOSED'}, T, 180) is None


class TestTLS:
    def test_parse_not_after(self):
        assert tls.parse_not_after('Jan  5 09:00:00 2027 GMT') == datetime(2027, 1, 5, 9, 0, 0)

    def test_no_domain(self):
        assert tls.check('')['error'] == 'no domain'

    def test_self_signed_is_not_valid(self, tmp_path):
        """A real TLS handshake against a local self-signed server must be reported as an error."""
        crypto = pytest.importorskip('cryptography')  # noqa: F841
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(1).not_valid_before(dt.datetime(2020, 1, 1)).not_valid_after(dt.datetime(2040, 1, 1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), False)
                .sign(key, hashes.SHA256()))
        cp, kp = tmp_path / 'c.pem', tmp_path / 'k.pem'
        cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        kp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
        sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        sctx.load_cert_chain(cp, kp)
        srv = socket.socket()
        srv.bind(('127.0.0.1', 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        def serve():
            conn, _ = srv.accept()
            try:
                sctx.wrap_socket(conn, server_side=True).close()
            except (ssl.SSLError, OSError):
                conn.close()
        th = threading.Thread(target=serve, daemon=True)
        th.start()
        res = tls.check('localhost', port, timeout=5)
        th.join(5)
        srv.close()
        assert res['error'] and 'not valid' in res['error'] and res['not_after'] is None
