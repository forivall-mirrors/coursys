# -*- coding: utf-8 -*-
# Generated by Django 1.10.5 on 2017-10-23 12:52
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grad', '0008_make_letter_template_slug_unique'),
    ]

    operations = [
        migrations.AddField(
            model_name='letter',
            name='removed',
            field=models.BooleanField(default=False),
        ),
    ]
