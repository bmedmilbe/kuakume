from django.conf import settings
from django.contrib.gis.db import models
from django.core.validators import MinLengthValidator, RegexValidator
from store.models import Street


class Deliver(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='delivery_profile'
    )
    location = models.PointField(srid=4326, null=True, blank=True)
    street = models.ForeignKey(
        Street, 
        on_delete=models.CASCADE, 
        related_name='delivers', 
        null=True, 
        blank=True
    )
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return f"Client: {self.user.username}"


class DeliverData(models.Model):
    class VerificationStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending Verification'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
    
    # Personal Information
    full_name = models.CharField(
        max_length=255, 
        verbose_name="Full Name",
        blank=False,  # Prevents empty strings in Django Forms/Admin
        null=False,   # Prevents NULL values in the database
        validators=[
            MinLengthValidator(5, message="Full name must be at least 10 characters long."),
            RegexValidator(
                regex=r'^\s*$', 
                inverse_match=True, 
                message="Full name cannot be empty or just spaces."
            )
        ]
    )

    def save(self, *args, **kwargs):
        # Forces model validation to run before saving to the database
        self.full_clean()
        super().save(*args, **kwargs)
    date_of_birth = models.DateField(
        verbose_name="Date of Birth"
    )
    residence = models.TextField(
        verbose_name="Residence Address"
    )
    street = models.ForeignKey(
        Street, 
        on_delete=models.CASCADE, 
        related_name='delivery_data_records'
    )
    deliver = models.OneToOneField(
        Deliver, 
        on_delete=models.CASCADE, 
        related_name='data_records'
    )
    
    # Identification Document (National ID / Bilhete de Identidade)
    document_number = models.CharField(
        max_length=50, 
        unique=True, 
        verbose_name="Document Number"
    )
    id_front = models.ImageField(
        upload_to="id_documents/front/", 
        verbose_name="ID Card Front"
    )
    id_back = models.ImageField(
        upload_to="id_documents/back/", 
        verbose_name="ID Card Back"
    )
    
    # Verification & Audit Fields
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        verbose_name="Verification Status"
    )
    approved_at = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Approved At"
    )
    # Updated to settings.AUTH_USER_MODEL to avoid the E301 error
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_delivery_records',
        verbose_name="Approved By",
    )

    def __str__(self):
        # Removed reliance on missing self.user reference in DeliverData
        return f"Client Data: {self.full_name} ({self.get_verification_status_display()})"
