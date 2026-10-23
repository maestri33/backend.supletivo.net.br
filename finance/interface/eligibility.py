"""A referral may earn commission before the promoter can receive a payout."""
from users.roles.promoter.models import Promoter


def can_receive(user, *, role, at):
    if role == "coordinator":
        return True
    if user is None:
        return False
    return Promoter.objects.filter(user=user, status=Promoter.Status.ACTIVE, activated_at__lte=at).exists()
