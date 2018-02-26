# Generated by Django 2.0.1 on 2018-02-26 14:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('outreach', '0009_on_delete'),
    ]

    operations = [
        migrations.AddField(
            model_name='outreachevent',
            name='enable_waitlist',
            field=models.BooleanField(default=False, help_text='If this box is checked and you have a registration cap which has been met, people will stillbe able to register but will be marked as not attending and waitlisted.'),
        ),
        migrations.AddField(
            model_name='outreacheventregistration',
            name='waitlisted',
            field=models.BooleanField(default=False, editable=False),
        ),
    ]
