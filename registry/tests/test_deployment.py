from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def read_yaml(relative: str):
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))


def test_base_compose_does_not_publish_application_ports_or_start_proxy():
    config = read_yaml("compose.yaml")
    assert set(config["services"]) == {"sub-store", "registry"}
    assert "ports" not in config["services"]["sub-store"]
    assert "ports" not in config["services"]["registry"]
    assert "container_name" not in str(config)
    assert config["name"] == "${COMPOSE_PROJECT_NAME:-loon-vps-cleaner}"


def test_standalone_overlay_is_the_only_mode_binding_public_ingress():
    config = read_yaml("deploy/compose.standalone.yaml")
    assert config["services"]["caddy"]["ports"] == ["80:80", "443:443"]
    assert "web" in config["services"]["registry"]["networks"]


def test_host_proxy_overlay_binds_registry_to_loopback_only():
    config = read_yaml("deploy/compose.host-proxy.yaml")
    assert config["services"]["registry"]["ports"] == [
        "127.0.0.1:${REGISTRY_HOST_PORT:-18765}:8000"
    ]
    assert "caddy" not in config["services"]


def test_docker_proxy_overlay_uses_existing_external_network_and_stable_alias():
    config = read_yaml("deploy/compose.docker-proxy.yaml")
    assert config["networks"]["proxy"]["external"] is True
    assert config["networks"]["proxy"]["name"] == "${PROXY_DOCKER_NETWORK}"
    assert config["services"]["registry"]["networks"]["proxy"]["aliases"] == [
        "loon-vps-cleaner-registry"
    ]
    assert "ports" not in config["services"]["registry"]


def test_installers_support_existing_docker_on_non_debian_linux():
    setup = (ROOT / "setup.sh").read_text(encoding="utf-8")
    bootstrap = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'case "$DISTRO_ID" in\n    debian|ubuntu)' in setup
    assert "if ! command -v docker" in setup
    assert "Existing Docker installations are never replaced" in setup
    assert "intended for Debian 12 only" not in bootstrap
    assert "Existing Docker installations are never replaced" in setup


def test_generated_server_configuration_examples_exist():
    expected = [
        "proxy-snippets/caddy-host.caddy.example",
        "proxy-snippets/caddy-docker.caddy.example",
        "proxy-snippets/nginx-host.locations.example",
        "proxy-snippets/nginx-docker.locations.example",
    ]
    for relative in expected:
        assert (ROOT / relative).is_file()


def test_docs_describe_all_proxy_modes_and_multi_site_isolation():
    docs = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    for phrase in ("Standalone", "Host Proxy", "Docker Proxy", "Debian", "Ubuntu", "独立 Compose project", "127.0.0.1"):
        assert phrase in docs
    assert "不会运行 `docker compose down`" in docs


def test_backup_preserves_local_deployment_mode_and_proxy_snippets():
    backup = (ROOT / "backup.sh").read_text(encoding="utf-8")
    assert "compose.override.yaml" in backup
    assert "proxy-snippets" in backup


def test_update_only_pulls_caddy_when_current_project_has_it():
    update = (ROOT / "update.sh").read_text(encoding="utf-8")
    assert "docker compose config --services" in update
    assert "grep -qx caddy" in update


def test_standalone_caddy_is_a_shared_multi_site_ingress():
    config = read_yaml("deploy/compose.standalone.yaml")
    caddy = config["services"]["caddy"]
    assert "host.docker.internal:host-gateway" in caddy["extra_hosts"]
    assert "./caddy-sites:/etc/caddy/sites:ro" in caddy["volumes"]
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")
    assert "import /etc/caddy/sites/*.caddy" in caddyfile
    setup = (ROOT / "setup.sh").read_text(encoding="utf-8")
    assert "caddy-sites" in setup
    backup = (ROOT / "backup.sh").read_text(encoding="utf-8")
    assert "caddy-sites" in backup
    assert "caddy-sites/*.caddy" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_admin_password_minimum_is_ten_characters_without_complexity_rules():
    setup = (ROOT / "setup.sh").read_text(encoding="utf-8")
    assert "Admin password (at least 10 characters)" in setup
    assert '[ "${#admin_password}" -ge 10 ]' in setup
    assert "at least 16 characters" not in setup
    assert "must include uppercase" not in setup.lower()


def test_dashboard_loads_sections_in_parallel_and_limits_page_size():
    js = (ROOT / "registry/static/app.js").read_text(encoding="utf-8")
    assert "Promise.allSettled([" in js
    assert 'page_size:"40"' in js
    app = (ROOT / "registry/app.py").read_text(encoding="utf-8")
    assert '@app.get("/api/status")\ndef status():' in app
    assert '@app.get("/api/nodes")\ndef list_nodes(' in app


def test_upgrader_updates_registry_only_and_backs_up_first():
    upgrade = (ROOT / "upgrade.sh").read_text(encoding="utf-8")
    assert 'bash "$INSTALL_DIR/backup.sh"' in upgrade
    assert '"$INSTALL_DIR/registry"' in upgrade
    assert 'docker compose up -d --no-deps --build registry' in upgrade
    assert 'docker compose down' not in upgrade
    assert 'docker system prune' not in upgrade


def test_node_list_uses_batched_dom_and_skips_offscreen_paint():
    js = (ROOT / "registry/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "registry/static/style.css").read_text(encoding="utf-8")
    assert "document.createDocumentFragment()" in js
    assert "$(\"nodes\").append(fragment)" in js
    assert "let nodesLoading = false" in js
    assert '$(\"page-next\").disabled = true' in js
    assert ".node-item{content-visibility:auto" in css
