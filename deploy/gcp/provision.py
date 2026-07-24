#!/usr/bin/env python3
"""Provision (or re-provision) the sysdx webapp on Google Compute Engine.

Why a plain VM and not a serverless / PaaS target: the sysdiagnose framework reads and
writes local filesystem paths throughout (it shells out to a native unifiedlog_iterator
binary, writes extracted case trees, graphviz output, etc.), and the worker needs the
same local disk the API serves from. A single VM with an attached persistent disk gives
that with no artificial per-volume size cap (the constraint that made a 500 MB PaaS
volume unworkable for real 100 MB+ sysdiagnose archives).

Topology this creates:
  - one GCE VM (Debian 12) running Docker
  - one persistent disk mounted at /data (case data + Postgres data live here)
  - Postgres 16 + the combined web/worker app container, app published on :80
  - a firewall rule opening :80

The heavy lifting (disk mount, image build, container run) is done by startup.sh, which
runs on the VM. This script just creates the GCP resources and hands startup.sh its
config via instance metadata. The webapp source is shipped to the VM through a GCS
bucket (the VM has clean, direct internet for the in-image `git clone` the Dockerfile
does; building locally behind a TLS-intercepting proxy does not).

Auth: set GOOGLE_APPLICATION_CREDENTIALS to a service-account key JSON with Compute +
Storage admin on the project. Requires `google-auth` and `requests`.

Usage:
    GOOGLE_APPLICATION_CREDENTIALS=key.json \
    python3 provision.py --project PROJECT_ID [--zone us-central1-a] \
        [--machine e2-standard-2] [--data-gb 20] --repo-root /path/to/sysdiagnose
"""
import argparse
import base64
import os
import secrets
import tarfile
import time

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def make_token():
    key = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    creds = service_account.Credentials.from_service_account_file(key, scopes=SCOPES)
    creds.refresh(Request())
    return creds.token, creds.project_id


def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def enable_apis(token, project):
    for api in ("compute", "storage", "storage-component"):
        requests.post(
            f"https://serviceusage.googleapis.com/v1/projects/{project}/services/{api}.googleapis.com:enable",
            headers=h(token),
        )


def project_number(token, project):
    r = requests.get(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{project}", headers=h(token)
    )
    r.raise_for_status()
    return r.json()["projectNumber"]


def pack_source(repo_root, out_path):
    """Tar the repo build context (Dockerfile context is the repo root)."""
    skip = {".git", "node_modules", "__pycache__", "dist", ".venv"}
    def flt(ti):
        parts = set(ti.name.split("/"))
        if parts & skip or ti.name.endswith(".pyc"):
            return None
        return ti
    with tarfile.open(out_path, "w:gz") as tar:
        tar.add(repo_root, arcname=".", filter=flt)


def upload_source(token, bucket, tar_path, project):
    body = {
        "name": bucket,
        "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}},
    }
    requests.post(
        f"https://storage.googleapis.com/storage/v1/b?project={project}", headers=h(token), json=body
    )  # 409 if it already exists — fine
    with open(tar_path, "rb") as f:
        r = requests.post(
            f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
            f"?uploadType=media&name=sysdx-src.tar.gz",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/gzip"},
            data=f.read(),
        )
    r.raise_for_status()


def grant_bucket_read(token, bucket, sa_email):
    pol = requests.get(
        f"https://storage.googleapis.com/storage/v1/b/{bucket}/iam", headers=h(token)
    ).json()
    pol.setdefault("bindings", []).append(
        {"role": "roles/storage.objectViewer", "members": [f"serviceAccount:{sa_email}"]}
    )
    requests.put(f"https://storage.googleapis.com/storage/v1/b/{bucket}/iam", headers=h(token), json=pol)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--repo-root", required=True, help="Path to the sysdiagnose repo (Docker build context)")
    ap.add_argument("--zone", default="us-central1-a")
    ap.add_argument("--machine", default="e2-standard-2")
    ap.add_argument("--data-gb", type=int, default=20)
    ap.add_argument("--name", default="sysdx-vm")
    args = ap.parse_args()

    token, _ = make_token()
    project = args.project
    zone = args.zone
    base = f"https://compute.googleapis.com/compute/v1/projects/{project}"

    print("enabling APIs...")
    enable_apis(token, project)
    time.sleep(5)
    pnum = project_number(token, project)
    sa_email = f"{pnum}-compute@developer.gserviceaccount.com"
    bucket = f"sysdx-deploy-{project}"

    print("packaging + uploading source...")
    tar_path = "/tmp/sysdx-src.tar.gz"
    pack_source(args.repo_root, tar_path)
    upload_source(token, bucket, tar_path, project)
    grant_bucket_read(token, bucket, sa_email)

    print("creating data disk...")
    requests.post(
        f"{base}/zones/{zone}/disks",
        headers=h(token),
        json={"name": "sysdx-data", "sizeGb": str(args.data_gb),
              "type": f"projects/{project}/zones/{zone}/diskTypes/pd-balanced"},
    )

    print("creating firewall (tcp:80)...")
    requests.post(
        f"{base}/global/firewalls",
        headers=h(token),
        json={"name": "sysdx-allow-http",
              "network": f"projects/{project}/global/networks/default",
              "direction": "INGRESS", "priority": 1000,
              "allowed": [{"IPProtocol": "tcp", "ports": ["80"]}],
              "sourceRanges": ["0.0.0.0/0"], "targetTags": ["sysdx"]},
    )

    # wait for disk
    for _ in range(30):
        r = requests.get(f"{base}/zones/{zone}/disks/sysdx-data", headers=h(token))
        if r.json().get("status") == "READY":
            break
        time.sleep(2)

    db_password = secrets.token_urlsafe(18)
    startup = open(os.path.join(os.path.dirname(__file__), "startup.sh")).read()

    print("creating VM...")
    inst = {
        "name": args.name,
        "machineType": f"zones/{zone}/machineTypes/{args.machine}",
        "tags": {"items": ["sysdx"]},
        "disks": [
            {"boot": True, "autoDelete": True, "initializeParams": {
                "sourceImage": "projects/debian-cloud/global/images/family/debian-12",
                "diskSizeGb": "20", "diskType": f"zones/{zone}/diskTypes/pd-balanced"}},
            {"source": f"projects/{project}/zones/{zone}/disks/sysdx-data",
             "deviceName": "sysdx-data", "autoDelete": False},
        ],
        "networkInterfaces": [{"network": f"projects/{project}/global/networks/default",
                               "accessConfigs": [{"type": "ONE_TO_ONE_NAT", "name": "External NAT"}]}],
        "serviceAccounts": [{"email": sa_email, "scopes": SCOPES}],
        "metadata": {"items": [
            {"key": "startup-script", "value": startup},
            {"key": "bucket", "value": bucket},
            {"key": "db-password", "value": db_password},
        ]},
    }
    r = requests.post(f"{base}/zones/{zone}/instances", headers=h(token), json=inst)
    r.raise_for_status()

    print("VM creating. Watch progress:")
    print(f"  gs://{bucket}/deploy-status.txt")
    print("Once healthy, the app is served on the VM's external IP, port 80.")


if __name__ == "__main__":
    main()
