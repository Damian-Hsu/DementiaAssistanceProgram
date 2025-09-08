# prefix
API_ROOT = "/api/v1"
AUTH_PREFIX = "/auth"
USER_PREFIX = "/users"
M2M_PREFIX = "/m2m"
ADMIN_PREFIX = "/admin"
JOBS_PREFIX = "/jobs"
CAMERA_PREFIX = "/camera"

# ========== routers methoda path ==========
#{router name}_{HTTP method}_{function name}
# APIService

# router.Authentication
AUTH_POST_SIGNUP = "/signup"
AUTH_POST_SIGNUP_ADMIN = "/signupadmin"
AUTH_POST_LOGIN = "/login"
M2M_GET_PING = "/ping"

# router.User
USER_GET_ME = "/me"
USER_PATCH_ME = "/me"
USER_PUT_ME_PASSWORD = "/me/password"

# router.Admin
ADMIN_POST_CREATE_KEY = "/api-keys"
ADMIN_GET_LIST_KEYS = "/api-keys"
ADMIM_PATCH_UPDATE_KEY = "/api-keys/{key_id}"
ADMIN_POST_ROTATE_KEY = "/api-keys/{key_id}/rotate"

# router.Jobs
JOBS_POST_CREATE_JOB = ""
JOBS_GET_GET_JOB = "/{job_id}"
JOBS_GET_GET_JOB_STATUS = "/{job_id}/status"