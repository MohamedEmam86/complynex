# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================

"""Safety checks of the secondary-instance shell tools (scripts/instance/, deploy.sh). Only refusal paths are
exercised: each must stop before it touches anything (users, databases, folders, systemd)."""

import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SI = os.path.join(ROOT, 'scripts', 'instance')


def _run(args, env=None):
    return subprocess.run(['bash'] + args, capture_output=True, text=True, timeout=60,
                          env={**os.environ, **(env or {})})


def test_remove_instance_refuses_reserved_names_and_the_main_database():
    for name in ('db', 'main', 'demo', 'complynex', 'postgres'):
        r = _run([os.path.join(SI, 'remove_instance.sh'), name, '--confirm', name])
        assert r.returncode == 2 and 'REFUSED' in r.stderr, (name, r.stderr)
    r = _run([os.path.join(SI, 'remove_instance.sh'), 'Bad_Name', '--confirm', 'Bad_Name'])
    assert r.returncode == 2 and 'invalid name' in r.stderr
    r = _run([os.path.join(SI, 'remove_instance.sh'), 'acme', '--confirm', 'other'])
    assert r.returncode == 2 and 'usage' in r.stderr


def test_remove_instance_needs_the_root_owned_list(tmp_path):
    src = open(os.path.join(SI, 'remove_instance.sh'), encoding='utf-8').read()
    assert 'LIST=/etc/complynex/instances.list' in src
    assert "awk -v n=\"$NAME\" '$1==n' \"$LIST\"" in src             # must be listed
    assert '[ -f "$INST/.cx_instance" ] || die' in src               # and carry the marker
    assert "RDB=$(echo \"$LINE\" | awk '{print $3}')" in src           # Redis db from the list, not the folder
    # every refusal comes before the first command that changes something
    first_change = min(src.index(x) for x in ('pg_dump', 'systemctl disable', 'dropdb', 'rm -rf', 'userdel'))
    assert all(src.index(x) < first_change for x in ('die "reserved name', "die \"$NAME is not in $LIST\"",
                                                    'die "database $DB is not an instance database"'))


def test_create_instance_refuses_an_unknown_profile_and_reserved_names():
    r = _run([os.path.join(SI, 'create_instance.sh'), 'acme', '8097', '7'], env={'PROFILE': 'govrenance'})
    assert r.returncode == 2 and 'unknown PROFILE' in r.stderr, r.stderr
    r = _run([os.path.join(SI, 'create_instance.sh'), 'db', '8097', '7'])
    assert r.returncode == 2 and 'reserved name' in r.stderr
    src = open(os.path.join(SI, 'create_instance.sh'), encoding='utf-8').read()
    assert "PASSWORD '$" not in src and ':\'pw\'' in src               # the DB password never on a command line
    assert '$G show "$REV:scripts/instance/backup_instance.sh"' in src  # backup script from the MAIN repo


def _update_instance_fn():
    src = open(os.path.join(ROOT, 'deploy.sh'), encoding='utf-8').read()
    a = src.index('update_instance() {')
    b = src.index('\n}\n', a) + 3
    return src[a:b]


def test_deploy_refuses_an_instance_with_a_tampered_gitdir_pointer(tmp_path):
    app = tmp_path / 'app'
    (app / '.git' / 'worktrees' / 'complynex-zz').mkdir(parents=True)
    script = tmp_path / 'u.sh'
    for case, make in (('wrong', lambda d: (d / '.git').write_text('gitdir: /tmp/evil\n')),
                       ('symlink', lambda d: (d / '.git').symlink_to(str(app / '.git' / 'worktrees' / 'complynex-zz'))),
                       ('missing', lambda d: None)):
        inst = tmp_path / case
        inst.mkdir()
        (inst / '.cx_instance').write_text('name=zz\n')
        make(inst)
        body = _update_instance_fn().replace('/var/www/complynex-$1', str(inst))
        script.write_text(f'APP={app}\nG="false"\nTARGET=abc\n{body}\nupdate_instance zz 8097; echo "rc=$?"\n')
        r = subprocess.run(['bash', str(script)], capture_output=True, text=True, timeout=60)
        assert 'REFUSED' in r.stdout and 'rc=1' in r.stdout, (case, r.stdout, r.stderr)


def test_deploy_uses_symlink_safe_chown_and_no_hooks():
    src = open(os.path.join(ROOT, 'deploy.sh'), encoding='utf-8').read()
    assert 'xargs -0 chown complynex' not in src and 'xargs -0 chown -h complynex:complynex' in src
    assert 'core.hooksPath=/dev/null' in _update_instance_fn()
    assert '--untracked-files=no' in _update_instance_fn()
    assert 'run_instances || true; exit 0' in src and '--instances-only' in src
