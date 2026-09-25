#!/usr/bin/env bash
set -euo pipefail

bundle=${1:?bundle directory required}
sysroot=/usr/x86_64-w64-mingw32/sys-root/mingw/bin
launcher_src=/src/default/patches/win-launcher.c

mkdir -p "${bundle}/bin" "${bundle}/lib"
shopt -s nullglob

# Turn Python entry-point scripts into native launchers without requiring
# environment.bat. The launcher deliberately resolves ..\\lib\\python3.exe.
python_scripts=()
for script in "${bundle}"/bin/* "${bundle}"/py3bin/*; do
	if [ -f "${script}" ] && head -1 "${script}" 2>/dev/null | grep -qi python; then
		python_scripts+=("${script}")
	fi
done

if [ ${#python_scripts[@]} -ne 0 ]; then
	x86_64-w64-mingw32-gcc -DGUI=0 -O2 -s -o "${bundle}/win-launcher.exe" "${launcher_src}"

	for script in "${python_scripts[@]}"; do
		if [[ ${script} == *-script.py ]]; then
			cp "${bundle}/win-launcher.exe" "${script%-script.py}.exe"
		else
			launcher="${script/.py/}.exe"
			wrapped="${script/.py/}-script.py"
			mv "${script}" "${wrapped}"
			cp "${bundle}/win-launcher.exe" "${launcher}"
		fi
	done
fi

if [ -d "${bundle}/py3bin" ]; then
	cp -f "${bundle}"/py3bin/* "${bundle}/lib/."
	rm -rf "${bundle}/py3bin"
fi
rm -f "${bundle}/win-launcher.exe"

find_dll() {
	local name=$1
	local path

	path=$(find "${bundle}" -type f -iname "${name}" -print -quit)
	if [ -n "${path}" ]; then
		printf '%s\n' "${path}"
		return
	fi

	find "${sysroot}" -maxdepth 1 -type f -iname "${name}" -print -quit
}

bundle_closure() {
	local root=$1
	local destination=$2
	local -a queue=("${root}")
	local -A seen=()
	local current dependency source target key
	local pos=0

	while [ ${pos} -lt ${#queue[@]} ]; do
		current=${queue[${pos}]}
		pos=$((pos + 1))
		key=$(readlink -f "${current}")

		if [ -n "${seen[${key}]+x}" ]; then
			continue
		fi
		seen[${key}]=1

		while IFS= read -r dependency; do
			[ -n "${dependency}" ] || continue
			source=$(find_dll "${dependency}")

			# DLLs not present in either the bundle or the MinGW sysroot are
			# Windows system libraries and are intentionally not bundled.
			if [ -z "${source}" ]; then
				continue
			fi

			target="${destination}/$(basename "${source}")"
			if [ ! -f "${target}" ]; then
				cp "${source}" "${target}"
			fi
			queue+=("${target}")
		done < <(
			x86_64-w64-mingw32-objdump -p "${current}" 2>/dev/null \
				| sed -n 's/^[[:space:]]*DLL Name:[[:space:]]*//p'
		)
	done
}

# Make every PE executable directly runnable by placing its non-system DLL
# dependency closure beside it. Process loadable PE modules as well so plugins
# do not silently retain dependencies on the cross toolchain environment.
while IFS= read -r -d '' binary; do
	bundle_closure "${binary}" "$(dirname "${binary}")"
done < <(
	find "${bundle}" -type f \
		\( -iname '*.exe' -o -iname '*.dll' -o -iname '*.pyd' -o -iname '*.so' \) \
		-print0
)
