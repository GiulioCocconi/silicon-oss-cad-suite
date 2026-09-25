#!/usr/bin/env python3

import click, signal, os, sys, shutil
from src.base import (
	OUTPUTS_ROOT,
	buildCode,
	cleanBuild,
	createBuildOrder,
	create_tar,
	getArchitecture,
	loadRules,
	pullCode,
	run_live,
	targets,
	validateArch,
	validateRules,
	validateTarget,
)

ARTIFACTS_ROOT = "_artifacts"
PACKAGES_ROOT = "_packages"


def force_shutdown(signum, frame):
	if (os.name != 'nt' and signum != signal.SIGPIPE):
		click.secho("\n==> Keyboard interrupt or external termination signal", fg="red", nl=True, bold=True)
	sys.exit(1)


def resolveReleaseTargets(root_targets, arch):
	resolved = []
	resolved_set = set()
	unresolved = set()

	def resolve(name):
		target = targets[name]

		if target.arch and arch not in target.arch:
			return
		if target.build_native or target.license_build_only:
			return
		if name in resolved_set:
			return
		if name in unresolved:
			raise click.ClickException("Circular runtime dependency involving '{}'.".format(name))

		unresolved.add(name)
		for dependency in target.dependencies + target.resources:
			resolve(dependency)
		unresolved.remove(name)

		if not target.top_package:
			resolved.append(name)
			resolved_set.add(name)

	for target in root_targets:
		resolve(target)

	return resolved


def createReleaseCache(target_names, arch, package_name):
	cache_nodes = set()
	for target_name in target_names:
		cache_nodes.update(createBuildOrder(target_name, arch, getArchitecture(), False))

	cache_paths = []
	for node_arch, node_name in sorted(cache_nodes):
		path = os.path.join(OUTPUTS_ROOT, node_arch, node_name)
		if not os.path.isdir(path):
			raise click.ClickException("Missing cache output: {}".format(path))
		cache_paths.append(path)

	os.makedirs(ARTIFACTS_ROOT, exist_ok=True)
	archive = os.path.abspath(os.path.join(
		ARTIFACTS_ROOT,
		"{}-cache-{}.tgz".format(package_name, arch),
	))

	params = [
		'tar',
		'--owner=root', '--group=root',
		'-czf', archive,
	] + cache_paths

	if run_live(params, cwd='.') != 0:
		raise click.ClickException("Failed to create build cache archive.")

	return archive


def deployWindows(stage_dir):
	params = [
		'docker',
		'run', '--rm',
	]

	if hasattr(os, 'getuid') and hasattr(os, 'getgid'):
		params += ['--user', '{}:{}'.format(os.getuid(), os.getgid())]

	params += [
		'-v', '{}:/bundle'.format(os.path.abspath(stage_dir)),
		'-v', '{}:/src:ro'.format(os.path.abspath('.')),
		'yosyshq/cross-windows-x64:2.3',
		'bash', '/src/scripts/deploy-windows.sh', '/bundle',
	]

	if run_live(params) != 0:
		raise click.ClickException("Failed to deploy Windows runtime dependencies.")


def packageRelease(target_names, arch, package_name):
	stage_dir = os.path.join(PACKAGES_ROOT, arch, package_name)
	if os.path.exists(stage_dir):
		shutil.rmtree(stage_dir)
	os.makedirs(stage_dir, exist_ok=True)

	for target_name in target_names:
		source_dir = os.path.join(OUTPUTS_ROOT, arch, target_name, "yosyshq")
		if not os.path.isdir(source_dir):
			raise click.ClickException(
				"Missing packaged output for {} [{}]: {}".format(target_name, arch, source_dir)
			)
		shutil.copytree(
			source_dir,
			stage_dir,
			dirs_exist_ok=True,
			symlinks=(arch != 'windows-x64'),
		)

	if arch == 'windows-x64':
		deployWindows(stage_dir)

	os.makedirs(ARTIFACTS_ROOT, exist_ok=True)
	archive_base = os.path.abspath(os.path.join(
		ARTIFACTS_ROOT,
		"{}-{}".format(package_name, arch),
	))

	if arch == 'windows-x64':
		archive = shutil.make_archive(archive_base, 'zip', root_dir=stage_dir)
	else:
		archive = archive_base + ".tgz"
		create_tar(archive, ".", stage_dir)

	return archive


def buildRelease(root_targets, arches, package_name, rules, no_update, nproc):
	for rule in rules.split(","):
		loadRules(rule)
	validateRules()

	for target in root_targets:
		validateTarget(target)
	for arch in arches:
		validateArch(arch)

	if not package_name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._" for c in package_name):
		raise click.ClickException("Package name may contain only letters, numbers, '-', '_' and '.'.")

	for arch in arches:
		release_targets = resolveReleaseTargets(root_targets, arch)
		if not release_targets:
			raise click.ClickException("No releasable targets for architecture {}.".format(arch))

		click.secho(
			"==> Release [{}]: {}".format(arch, ", ".join(release_targets)),
			fg="green",
			bold=True,
		)

		for target in release_targets:
			pullCode(target, arch, getArchitecture(), no_update, False)
			buildCode(target, arch, nproc, False, False, False, False, False)

		package_archive = packageRelease(release_targets, arch, package_name)
		cache_archive = createReleaseCache(release_targets, arch, package_name)

		click.secho("==> Package: {}".format(package_archive), fg="green", bold=True)
		click.secho("==> Cache:   {}".format(cache_archive), fg="green", bold=True)


@click.group(help="""OSS CAD Suite Builder\n""", context_settings=dict(help_option_names=["-h", "--help"]), invoke_without_command=True)
@click.pass_context
def cli(ctx):
	ctx.ensure_object(dict)
	if ctx.invoked_subcommand is None:
		click.secho(ctx.get_help())
	pass


@cli.command()
@click.option('--no-update', help='Do not update source files.', is_flag=True)
@click.option('--force', help='Force build of specified target.', is_flag=True)
@click.option('--target', default='default', show_default=True, help='Target project to build.')
@click.option('--arch', default=getArchitecture(), show_default=True, help='Build architecture.')
@click.option('--rules', default='default', show_default=True, help='Comma separated list of rules to use.')
@click.option('--dry', help='Just dry run of packages to be built', is_flag=True)
@click.option('--src', help='Pack sources where applicable', is_flag=True)
@click.option('--single', help='Single target build (for CI only)', is_flag=True)
@click.option('--tar', help='Single target package (for CI only)', is_flag=True)
@click.option('-j', '--nproc', default=os.cpu_count(), show_default=True, help='Number of build process.')
def build(no_update, force, target, arch, rules, dry, src, single, tar, nproc):
	"""Build tools"""
	for rule in rules.split(","):
		loadRules(rule)
	validateRules()
	validateTarget(target)
	validateArch(arch)
	pullCode(target, arch, getArchitecture(), no_update, single)
	buildCode(target, arch, nproc, force, dry, src, single, tar)


@cli.command()
@click.option('--no-update', help='Do not update source files.', is_flag=True)
@click.option('--target', 'release_targets', multiple=True, required=True, help='Target to include. May be specified multiple times.')
@click.option('--arch', 'release_arches', multiple=True, required=True, help='Release architecture. May be specified multiple times.')
@click.option('--name', 'package_name', default='silicon-oss', show_default=True, help='User-facing package name.')
@click.option('--rules', default='default', show_default=True, help='Comma separated list of rules to use.')
@click.option('-j', '--nproc', default=os.cpu_count(), show_default=True, help='Number of build process.')
def release(no_update, release_targets, release_arches, package_name, rules, nproc):
	"""Build selected targets and create user and build-cache archives."""
	buildRelease(release_targets, release_arches, package_name, rules, no_update, nproc)


@cli.command()
@click.option('--arch', default=getArchitecture(), show_default=True, help='Build architecture.')
@click.option('--full', help='Remove all architectures and sources as well.', is_flag=True)
def clean(arch, full):
	"""Clean build"""
	cleanBuild(arch, full)


@cli.command()
@click.option('--target', default='default', show_default=True, help='Target project to build.')
@click.option('--arch', default=getArchitecture(), show_default=True, help='Build architecture.')
@click.option('--rules', default='default', show_default=True, help='Comma separated list of rules to use.')
def source(target, arch, rules):
	"""Update sources"""
	for rule in rules.split(","):
		loadRules(rule)
	validateRules()
	validateTarget(target)
	validateArch(arch)
	pullCode(target, arch, getArchitecture(), False, False)


if __name__ == '__main__':
	if os.name == "posix":
		signal.signal(signal.SIGHUP, force_shutdown)
		signal.signal(signal.SIGPIPE, force_shutdown)
	signal.signal(signal.SIGINT, force_shutdown)
	signal.signal(signal.SIGTERM, force_shutdown)

	cli(None)
