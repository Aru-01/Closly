from rest_framework import serializers
from users.models import Invite


class InviteSerializer(serializers.ModelSerializer):
    """
    Serializer for displaying user invite codes and redemption status.
    """
    is_used = serializers.SerializerMethodField()

    class Meta:
        model = Invite
        fields = [
            'code',
            'kind',
            'is_used',
            'used_at',
            'expires_at',
            'created_at',
        ]
        read_only_fields = fields

    def get_is_used(self, obj) -> bool:
        return bool(obj.used_by_id or obj.used_at)


class InviteRedeemInputSerializer(serializers.Serializer):
    """
    Serializer for validating single-use invite redemption requests.
    """
    code = serializers.CharField(
        required=True,
        max_length=64,
        trim_whitespace=True,
        help_text="Single-use invite access code",
    )
