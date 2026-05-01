import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from savings.models import Family, FamilyMembership

User = get_user_model()


def _user(username: str):
    return User.objects.create_user(username=username, password="pw")


@pytest.mark.django_db
def test_family_membership_clean_rejects_user_already_in_another_family():
    owner = _user("owner_fm_clean")
    member = _user("member_fm_clean")
    fam_a = Family.objects.create(created_by=owner)
    fam_b = Family.objects.create(created_by=owner)
    FamilyMembership.objects.create(family=fam_a, user=member)
    duplicate = FamilyMembership(family=fam_b, user=member)
    with pytest.raises(ValidationError) as exc:
        duplicate.full_clean()
    assert "only one family" in str(exc.value).lower()
