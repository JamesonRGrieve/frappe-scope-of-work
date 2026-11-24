#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Runs the app's whole test suite on a throwaway ERPNext v16 bench in podman: MariaDB, Redis and the
# official ERPNext image with this working tree installed as an app on a fresh site.
#
#   tools/test-bench.sh up      build the bench and install the app (once)
#   tools/test-bench.sh test    copy the working tree in again and run the suite
#   tools/test-bench.sh serve   serve the site's desk on http://127.0.0.1:$BENCH_PORT (needs BENCH_PORT at `up`)
#   tools/test-bench.sh down    remove everything `up` created
#
# Every name starts with $BENCH_PREFIX, so two checkouts never collide.
main() {
	set -euo pipefail
	local root prefix network db redis bench site
	root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
	prefix="${BENCH_PREFIX:-scope-of-work-test}"
	network="$prefix-net"
	db="$prefix-db"
	redis="$prefix-redis"
	bench="$prefix-bench"
	site="scope-of-work.test"
	local erpnext_image="docker.io/frappe/erpnext:v16.36.1"
	local db_image="docker.io/library/mariadb:11.8"
	local redis_image="docker.io/library/redis:7-alpine"
	local db_root_password="bench-root"
	local admin_password="bench-admin"
	local db_ready_attempts=120
	local serve_port=8000
	local app_dir="/home/frappe/frappe-bench/apps/scope_of_work"

	in_bench() {
		podman exec -i -u 1000:1000 -w /home/frappe/frappe-bench "$bench" "$@"  # by uid: podman sometimes stops resolving the name
	}

	# The working tree (tracked and untracked files, nothing ignored) replaces the app's source in the bench.
	copy_app() {
		podman exec -u 0 "$bench" mkdir -p "$app_dir"
		git -C "$root" ls-files -z --cached --others --exclude-standard \
			| tar -C "$root" --null -T - -cf - \
			| podman exec -i -u 0 "$bench" tar -C "$app_dir" -xf -
		podman exec -u 0 "$bench" chown -R frappe:frappe "$app_dir"
	}

	case "${1:-}" in
	up)
		podman network create "$network" >/dev/null
		podman run -d --name "$db" --network "$network" --network-alias db \
			-e MARIADB_ROOT_PASSWORD="$db_root_password" "$db_image" \
			--character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci \
			--skip-character-set-client-handshake >/dev/null
		podman run -d --name "$redis" --network "$network" --network-alias redis "$redis_image" >/dev/null
		local publish=()
		if [ -n "${BENCH_PORT:-}" ]; then
			publish=(-p "127.0.0.1:$BENCH_PORT:$serve_port")
		fi
		podman run -d --name "$bench" --network "$network" "${publish[@]}" --entrypoint sleep "$erpnext_image" infinity >/dev/null
		local attempt
		for attempt in $(seq "$db_ready_attempts"); do
			if podman exec "$db" mariadb-admin ping -h 127.0.0.1 --protocol=tcp -uroot \
				-p"$db_root_password" --silent >/dev/null 2>&1; then
				break
			fi
			if [ "$attempt" = "$db_ready_attempts" ]; then
				echo "MariaDB never became ready" >&2
				exit 1
			fi
			sleep 1
		done
		copy_app
		in_bench bench set-config -g db_host db
		in_bench bench set-config -g redis_cache redis://redis:6379/0
		in_bench bench set-config -g redis_queue redis://redis:6379/1
		in_bench bench set-config -g redis_socketio redis://redis:6379/2
		in_bench ./env/bin/python -m pip install --quiet -e apps/scope_of_work
		# The image's apps.txt has no final newline.
		in_bench bash -c 'grep -qx scope_of_work sites/apps.txt || printf "\nscope_of_work\n" >> sites/apps.txt'
		in_bench bench new-site "$site" --mariadb-root-password "$db_root_password" \
			--admin-password "$admin_password" --mariadb-user-host-login-scope='%' --install-app erpnext
		in_bench bench --site "$site" install-app scope_of_work
		in_bench bench --site "$site" set-config allow_tests true
		;;
	test)
		copy_app
		in_bench bench --site "$site" migrate
		in_bench bench --site "$site" run-tests --app scope_of_work
		;;
	serve)
		# The image keeps its built assets beside sites/, which is a volume, so the link to them is missing.
		in_bench ln -sfn /home/frappe/frappe-bench/assets sites/assets
		# A fresh site sends every System Manager to the setup wizard; mark it set up so the desk opens.
		in_bench bench --site "$site" console <<-'PYTHON' >/dev/null
			frappe.db.sql("update `tabInstalled Application` set is_setup_complete = 1")
			frappe.db.set_default("setup_complete", 1)
			frappe.db.set_default("desktop:home_page", "desktop")
			frappe.db.commit()
			frappe.clear_cache()
		PYTHON
		in_bench bench use "$site"
		in_bench bench serve --port "$serve_port"
		;;
	down)
		podman rm -f "$bench" "$redis" "$db" >/dev/null
		podman network rm "$network" >/dev/null
		;;
	*)
		echo "usage: $0 up|test|serve|down" >&2
		exit 2
		;;
	esac
}
main "$@"
