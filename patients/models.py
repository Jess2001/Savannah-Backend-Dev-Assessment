from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
# Create your models here.
class Patient(models.Model):
    """
    Acts as a domain-specific profile extension of the core User identity.
    Ensures structural separation between authentication credentials and patient business logic.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='patient_profile',
        help_text="Link to the underlying Django authentication user record."
    )
    phone_number = models.CharField(max_length=15, blank=True, default="", help_text="Patient's contact phone number.")
    # Future clinical extensions (e.g., insurance_policy_number, date_of_birth) belong here.
    
    def clean(self):
        super().clean()
        if self.user_id and self.user.role != self.user.Role.PATIENT:
            raise ValidationError({"user": "Linked user must have the PATIENT role."})
    def __str__(self):
        return f"Patient: {self.user.get_full_name() or self.user.username}"
