# Copyright 2018 Google Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
  Package for shared methods among the commands
"""

import os
import shutil
import subprocess
from glob import glob

import click

from crmint_commands.utils import constants

IGNORE_PATTERNS = ("^.idea", "^.git", "*.pyc", "frontend/node_modules",
                   "backends/data/*.json")


def execute_command(step_name, commands, cwd='.', report_empty_err=True):
  click.echo(click.style("---> %s" % step_name, fg='blue', bold=True))
  pipe = subprocess.Popen(commands,
                   cwd=cwd,
                   shell=True,
                   stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE)
  out, err = pipe.communicate()
  if pipe.returncode != 0 and (len(err) > 0 or report_empty_err):
    msg = "\n%s: %s %s" % (step_name, err, ("({})".format(out) if out else ''))
    click.echo(click.style(msg, fg="red", bold=True))
    click.echo(click.style("Command: %s\n" % commands, bold=False))
  return pipe.returncode, out, err


def get_default_stage_name():
  gcloud_command = "$GOOGLE_CLOUD_SDK/bin/gcloud --quiet"
  commands = [
      "{gcloud_bin} config get-value project 2>/dev/null".format(
          gcloud_bin=gcloud_command)
  ]
  status, out, err = execute_command("Get current project identifier", commands)
  if status != 0:
    exit(1)
  stage_name = out.strip()
  return stage_name


def get_stage_file(stage_name):
  stage_file = "{}/{}.py".format(constants.STAGE_DIR, stage_name)
  return stage_file


def check_stage_file(stage_name):
  stage_file = get_stage_file(stage_name)
  if not os.path.isfile(stage_file):
    return False
  return True


def get_stage_object(stage_name):
  return getattr(__import__("stage_variables.%s" % stage_name), stage_name)


def get_service_account_file(stage):
  filename = stage.service_account_file
  service_account_file = os.path.join(constants.SERVICE_ACCOUNT_PATH, filename)
  return service_account_file


def check_service_account_file(stage):
  service_account_file = get_service_account_file(stage)
  if not os.path.isfile(service_account_file):
    return False
  return True


def before_hook(stage, stage_name):
  """
    Method that adds variables to the stage object
    and prepares the working directory
  """
  stage.stage_name = stage_name

  # Working directory to prepare deployment files.
  if not stage.workdir:
    stage.workdir = "/tmp/{}".format(stage.project_id_gae)

  # Set DB connection variables.
  stage.db_instance_conn_name = "{}:{}:{}".format(
      stage.project_id_gae,
      stage.project_region,
      stage.db_instance_name)

  stage.cloudsql_dir = "/tmp/cloudsql"
  stage.cloud_db_uri = "mysql+mysqldb://{}:{}@/{}?unix_socket=/cloudsql/{}".format(
      stage.db_username, stage.db_password,
      stage.db_name, stage.db_instance_conn_name)

  stage.local_db_uri = "mysql+mysqldb://{}:{}@/{}?unix_socket={}/{}".format(
      stage.db_username, stage.db_password, stage.db_name,
      stage.cloudsql_dir, stage.db_instance_conn_name)
  target_dir = stage.workdir
  try:
    if os.path.exists(target_dir):
      shutil.rmtree(target_dir)

    # Copy source code to the working directory.
    shutil.copytree(constants.PROJECT_DIR, target_dir,
                    ignore=shutil.ignore_patterns(IGNORE_PATTERNS))
  except Exception as exception:
    raise Exception("Stage 1 error when copying to workdir: %s" % exception.message)

  try:
    # Create DB config for App Engine application in the cloud.
    db_config_path = "%s/backends/instance/config.py" % stage.workdir
    with open(db_config_path, "w") as db_file:
      db_file.write("SQLALCHEMY_DATABASE_URI=\"%s\"" % stage.cloud_db_uri)
  except Exception as exception:
    raise Exception("Stage 1 error when writing db config: %s" % exception.message)
  try:
    # Delete service account example file.
    for file_name in glob("%s/backends/data/service-account.json.*" % stage.workdir):
      os.remove(file_name)
  except Exception as exception:
    raise Exception("Stage 1 error when copying service account file: %s" % exception.message)
  try:
    # Make app_data.json for backends.
    with open("%s/backends/data/app.json" % stage.workdir, "w") as app_file:
      app_file.write("""
              {
                "notification_sender_email": "$notification_sender_email",
                "app_title": "$app_title"
              }
              """)
  except Exception as exception:
    raise Exception("Stage 1 error when writing app data for backend: %s" % exception.message)
  try:
    # Make environment.prod.ts for frontend
    with open("%s/frontend/src/environments/environment.prod.ts" % stage.workdir, "w") as ts_file:
      ts_file.write("""
              export const environment = {
                production: true,
                app_title: "$app_title",
                enabled_stages: $enabled_stages
              }
              """)
  except Exception as exception:
    raise Exception("Stage 1 error when writing env data for frontend: %s" % exception.message)
  return stage


def check_variables():
  if not os.environ.get("GOOGLE_CLOUD_SDK", None):
    gcloud_path = subprocess.Popen("gcloud --format='value(installation.sdk_root)' info",
                                   shell=True, stdout=subprocess.PIPE)
    os.environ["GOOGLE_CLOUD_SDK"] = gcloud_path.communicate()[0].strip()
  # Cloud sql proxy
  cloud_sql_proxy_path = "/usr/bin/cloud_sql_proxy"
  home_path = os.environ["HOME"]
  if os.path.isfile(cloud_sql_proxy_path):
    os.environ["CLOUD_SQL_PROXY"] = cloud_sql_proxy_path
  else:
    cloud_sql_proxy = "{}/bin/cloud_sql_proxy".format(home_path)
    if not os.path.isfile(cloud_sql_proxy):
      click.echo("\rDownloading cloud_sql_proxy to ~/bin/", nl=False)
      os.mkdir("{}/bin".format(home_path), 0755)
      cloud_sql_download_link = "https://dl.google.com/cloudsql/cloud_sql_proxy.linux.amd64"
      download_command = "curl -L {} -o {}".format(cloud_sql_download_link,
                                                   os.environ["CLOUD_SQL_PROXY"])
      download_status = subprocess.Popen(download_command,
                                         shell=True,
                                         stdout=subprocess.PIPE).communicate()[0]
      if download_status != 0:
        click.echo("[w]Could not download cloud sql proxy")
    os.environ["CLOUD_SQL_PROXY"] = cloud_sql_proxy


def before_task(stage, use_service_account):
  if os.path.exists(stage.cloudsql_dir):
    shutil.rmtree(stage.cloudsql_dir)
  os.mkdir(stage.cloudsql_dir)
  with open("{}/backends/instance/config.py".format(stage.workdir), "w") as config:
    config.write("SQLALCHEMY_DATABASE_URI=\"{}\"".format(stage.local_db_uri))
  db_command = ""
  if use_service_account:
    db_command = "{} -projects={} -instances={} -dir={} -credential_file={}".format(
        os.environ["CLOUD_SQL_PROXY"], stage.project_id_gae, stage.db_instance_conn_name,
        stage.cloudsql_dir, os.path.join(constants.SERVICE_ACCOUNT_PATH,
                                         constants.SERVICE_ACCOUNT_DEFAULT_FILE_NAME))
  else:
    db_command = "{} -projects={} -instances={} -dir={} -credential_file={}".format(
        os.environ["CLOUD_SQL_PROXY"], stage.project_id_gae, stage.db_instance_conn_name,
        stage.cloudsql_dir, os.path.join(constants.SERVICE_ACCOUNT_PATH,
                                         stage.service_account_file))
  return subprocess.Popen((db_command,
                           "export FLASK_APP=\"{}/backends/run_ibackend.py\"".format(stage.workdir),
                           "export PYTHONPATH=\"{}/platform/google_appengine:lib\"".format(
                               os.environ["GOOGLE_CLOUD_SDK"]),
                           "export APPLICATION_ID=\"{}\"".format(stage.project_id_gae)),
                          preexec_fn=os.setsid, shell=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)


def install_requirements():
  try:
    resp = subprocess.Popen("pip install -r {} -t {}".format(constants.REQUIREMENTS_DIR,
                                                             constants.LIB_DEV_PATH),
                     stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE,
                     shell=True)
  except:
    raise Exception("Requirements could not be installed")
