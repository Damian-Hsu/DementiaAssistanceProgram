from enum import Enum
from sqlalchemy import Enum as SAEnum

# =============== Users Tabel usage ===============
class Role(str, Enum):
    user = "user"
    admin = "admin"

class Gender(str, Enum):
    male = "male"
    female = "female"
# =============== Compute_Jobs Tabel usage ===============
class JobStatus(str, Enum):
    pending = "pending"
    processing  = "processing" 
    success = "success"
    failed = "failed"

RoleEnum = SAEnum(Role, name="role_enum")
GenderEnum = SAEnum(Gender, name="gender_enum")
JobStatusEnum = SAEnum(JobStatus, name="job_status_enum")

# =============== Recordings Tabel usage ===============

class UploadStatus(str, Enum):
    pending = "pending"
    success = "success"
    failed = "failed"

UploadStatusEnum = SAEnum(UploadStatus, name="upload_status_enum")

# =============== Camera Tabel usage ===============
class CameraStatus(str, Enum):
    inactive = "inactive"
    active = "active"
    deleted = "deleted"

CameraStatusEnum = SAEnum(CameraStatus, name="camera_status_enum")