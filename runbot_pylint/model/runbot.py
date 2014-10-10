#!/usr/bin/python
# -*- encoding: utf-8 -*-
#
#    Module Writen to OpenERP, Open Source Management Solution
#
#    Copyright (c) 2014 Vauxoo - http://www.vauxoo.com/
#    All Rights Reserved.
#    info Vauxoo (info@vauxoo.com)
#
#    Coded by: vauxoo consultores (info@vauxoo.com)
#
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
"""
This module is used to create new fields in the inherited classes.
"""
from openerp.osv import fields, osv
import logging
import os
import stat

_logger = logging.getLogger(__name__)


def get_depends(modules, addons_paths, depends=None):
    if depends is None:
        depends = []
    for module in (modules or '').split(','):
        if not module in depends:
            depends.append(module)
            for addons_path in (addons_paths or '').split(','):
                addons_path = addons_path.strip()
                fname_openerp = os.path.join(addons_path, module, '__openerp__.py')
                if os.path.isfile(fname_openerp):
                    module_depends_list = eval(open(fname_openerp, "r").read()).get('depends', [])
                    if module_depends_list:
                        module_depends_str = ','.join(module_depends_list)
                        get_depends(module_depends_str, addons_paths, depends=depends)
    return depends


class RunbotRepo(osv.osv):

    """
    Added pylint_config field to use a configuration of pylint by repository,
    to use for each build of repository.
    """

    _inherit = 'runbot.repo'

    _columns = {
        'pylint_config': fields.many2one('pylint.conf',
                                         string='Pylint Config'),
        'check_pylint': fields.boolean(string='Check pylint'),
    }


class RunbotBranch(osv.osv):

    """
    Added pylint_config field to use a configuration of pylint by repository,
    to use for each build of repository.
    """

    _inherit = 'runbot.branch'

    def get_module_list(self, cr, uid, ids, sha=None, context=None):
        repo_paths_list = []
        for branch in self.browse(cr, uid, ids, context=context):
            command_git = ['ls-tree', sha or branch.branch_name, '--name-only']
            if branch.repo_id.type == 'main':
                command_git.append('addons/')
                command_git.append('openerp/addons/')
            repo_paths_str = branch.repo_id.git(command_git)
            repo_paths_list = repo_paths_str and repo_paths_str.rstrip().split('\n') or []
            repo_paths_list = [os.path.basename(module) for module in repo_paths_list]
        return repo_paths_list


class RunbotBuild(osv.osv):

    """
    Added pylint_config field, used by default the configuration of repository.
    """

    _inherit = "runbot.build"

    _columns = {
        'pylint_config': fields.many2one('pylint.conf',
                                         string='Pylint Config'),
    }

    def create(self, cr, uid, values, context=None):
        """
        This method set configuration of pylint.
        """
        new_id = super(RunbotBuild, self).create(cr, uid, values,
                                                 context=context)
        if values.get('branch_id', False) and not values\
                .has_key('pylint_config'):
            branch_id = self.pool.get('runbot.branch').browse(cr, uid,
                                                         values['branch_id'])
            self.write(
                cr, uid, [new_id],
                {'pylint_config': branch_id.repo_id and
                 branch_id.repo_id.pylint_config and
                 branch_id.repo_id.pylint_config.id or False}, context=context)
        return new_id

    def get_repo_build_paths(self, cr, uid, build_id, repo_id, filter_files=None,
            filter_dirs=None, isdir=True, check_module_depends=True, context=None):
        repo_pool = self.pool['runbot.repo']
        repo = repo_pool.browse(cr, uid, [repo_id], context=context)[0]
        build = self.browse(cr, uid, [build_id], context=context)[0]
        # TODO: Add version or sha and replace by master
        version_build = build.branch_id and build.branch_id.branch_base_name or build.branch_id.branch_name
        #import pdb;pdb.set_trace()
        command_git = ['ls-tree', version_build, '--name-only']
        if repo.type == 'main':
            command_git.append('addons/')
        repo_paths_str = repo.git(command_git)
        repo_paths_list = repo_paths_str and repo_paths_str.rstrip().replace('addons/', '').split('\n') or []
        paths = []
        if repo_paths_list:
            # if repo.type == 'main':
            base_path = build.server('addons')
            if base_path:
                for repo_path in repo_paths_list:
                    repo_full_path = os.path.join(base_path, repo_path)
                    if os.path.isdir(repo_full_path) and isdir:
                        paths.append(repo_full_path)
                    elif os.path.isfile(repo_full_path) and \
                            (os.path.splitext(repo_full_path)[1] in filter_files or not filter_files):
                        paths.append(repo_full_path)
        return paths

    #job_10_test_base = lambda self, cr, uid, build, lock_path, log_path, args=None: build.checkout()

    def job_15_pylint(self, cr, uid, build, lock_path, log_path, args=None):
        """
        This method is used to run pylint test, getting parameters of the
        pylint configuration, the parameters errors and files to ignore has
        send in list structures to method _run_test_pylint.

        :param build: object build of runbot.
        :param lock_path: path of lock file, this parameter is string.
        :param log_path: path of log file, this parameter is string, where are
                            has saved the log of test.
        :param args: this parameter not is required, not is used.
        """
        if args == None:
            args = {}
        build._log('pylint_script', 'Start pylint script')
        result = False
        dep = []
        if build.pylint_config:
            if build.pylint_config.conf_file:
                path_pylint_conf = os.path\
                    .join(os.path.split(build.server())[0],
                    build.pylint_config.conf_file)

                _, modules = build.cmd()
                dep = get_depends(modules, build.server('addons'))

                repo_module_to_check_pylint = []
                for build_line in build.line_ids:
                    if build_line.repo_id.check_pylint:
                        branch_ls = build_line.branch_id.get_module_list(build_line.sha)
                        repo_module_to_check_pylint.extend(branch_ls)
                modules_to_check_pylint = list(set(dep) & set(repo_module_to_check_pylint))

                if modules_to_check_pylint:
                    fname_pylint_run_sh = os.path.join(build.path(), 'pylint_run.sh')
                    with open(fname_pylint_run_sh, "w") as f_pylint_run_sh:
                        f_pylint_run_sh.write("#!/bin/bash\n")
                        f_pylint_run_sh.write("export PYTHONPATH=$PYTHONPATH:%s\n" % (build.server()))
                        for module_to_check_pylint in modules_to_check_pylint:
                            cmd = "pylint --rcfile=%s %s" % (path_pylint_conf,
                                os.path.join(build.server('addons'), module_to_check_pylint))
                            #os.environ['PYTHONPATH'] = os.environ.get('PYTHONPATH', '') + ":" + build.server()
                            f_pylint_run_sh.write(cmd + '\n')

                        fname_custom_pylint_run = os.path.join(build.path(), "check_ast/check_print_and_pdb.py")
                        if os.path.isfile(fname_custom_pylint_run):
                            for module_to_check_pylint in modules_to_check_pylint:
                                cmd = "%s %s" % (fname_custom_pylint_run,
                                    os.path.join(build.server('addons'),
                                    module_to_check_pylint))
                                f_pylint_run_sh.write(cmd + '\n')

                    st = os.stat(fname_pylint_run_sh)
                    os.chmod(fname_pylint_run_sh, st.st_mode | stat.S_IEXEC)
                    return build.spawn([fname_pylint_run_sh], lock_path, log_path, cpu_limit=2100)
        return result

    def job_30_run(self, cr, uid, build, lock_path, log_path):
        res = super(RunbotBuild, self).job_30_run(cr, uid, build, lock_path,
                     log_path)
        pylint_log = build.path('logs', 'job_15_pylint.txt')
        pylint_error = False
        max_log_lines = 20
        count = 0
        if os.path.isfile(pylint_log):
            with open(pylint_log, "r") as fpylint_log:
                for line in fpylint_log.xreadlines():
                    if not pylint_error and '****' in line:
                        pylint_error = True
                    if pylint_error:
                        self.pool['ir.logging'].create(cr, uid, {
                            'build_id': build.id,
                            'level': 'WARNING',
                            'type': 'runbot',
                            'name': 'odoo.runbot',
                            'message': line,
                            'path': 'runbot',
                            'func': 'pylint result',
                            'line': '0',
                        })
                        count += 1
                        if count >= max_log_lines:
                            build._log('pylint_script', 'pylint has many '
                              'errors. Please check pylint full log file...')
                            break
        if pylint_error and build.result == "ok":
            build.write({'result': 'warn'})
        return res