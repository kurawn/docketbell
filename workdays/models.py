from django.db import models

from core.models import BaseModel


class BankHoliday(BaseModel):
    region = models.CharField(max_length=32)
    date = models.DateField()
    title = models.CharField(max_length=200)

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["region", "date"], name="uniq_holiday_region_date")]
