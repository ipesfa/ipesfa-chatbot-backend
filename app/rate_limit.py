from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# storage_uri="memory://" solo cuenta correctamente con 1 proceso Passenger.
# Al crear el Python App en cPanel, dejar "Number of processes" = 1.
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
