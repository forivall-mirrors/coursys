# -*- coding: utf-8 -*-
# Generated by Django 1.11.9 on 2018-01-18 17:09
from __future__ import unicode_literals

import autoslug.fields
import django.core.files.storage
from django.db import migrations, models
import django.db.models.deletion
import space.models


class Migration(migrations.Migration):

    dependencies = [
        ('space', '0005_add_notes_to_booking_records'),
    ]

    operations = [
        migrations.AlterField(
            model_name='bookingmemo',
            name='booking_record',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='memos', to='space.BookingRecord'),
        ),
        migrations.AlterField(
            model_name='bookingmemo',
            name='created_by',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='coredata.Person'),
        ),
        migrations.AlterField(
            model_name='bookingrecord',
            name='form_submission_URL',
            field=models.CharField(blank=True, help_text='If the user filled in a form to get this booking created, put its URL here.', max_length=1000, null=True),
        ),
        migrations.AlterField(
            model_name='bookingrecord',
            name='last_modified_by',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='coredata.Person'),
        ),
        migrations.AlterField(
            model_name='bookingrecord',
            name='location',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bookings', to='space.Location'),
        ),
        migrations.AlterField(
            model_name='bookingrecord',
            name='person',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='coredata.Person'),
        ),
        migrations.AlterField(
            model_name='bookingrecord',
            name='slug',
            field=autoslug.fields.AutoSlugField(editable=False, populate_from='autoslug', unique=True),
        ),
        migrations.AlterField(
            model_name='bookingrecordattachment',
            name='booking_record',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='attachments', to='space.BookingRecord'),
        ),
        migrations.AlterField(
            model_name='bookingrecordattachment',
            name='contents',
            field=models.FileField(max_length=500, storage=django.core.files.storage.FileSystemStorage(base_url=None, location='submitted_files'), upload_to=space.models.space_attachment_upload_to),
        ),
        migrations.AlterField(
            model_name='bookingrecordattachment',
            name='created_by',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='coredata.Person'),
        ),
        migrations.AlterField(
            model_name='bookingrecordattachment',
            name='slug',
            field=autoslug.fields.AutoSlugField(editable=False, populate_from='title', unique_with=('booking_record',)),
        ),
        migrations.AlterField(
            model_name='location',
            name='building',
            field=models.CharField(blank=True, choices=[('ASB', 'Applied Sciences Building'), ('TASC1', 'TASC 1'), ('SRY', 'Surrey'), ('SEE', 'SEE Building'), ('PTECH', 'Powertech'), ('BLARD', 'Ballard'), ('CC1', 'CC1'), ('NTECH', 'NEUROTECH'), ('SMH', 'SMH')], max_length=5, null=True),
        ),
        migrations.AlterField(
            model_name='location',
            name='campus',
            field=models.CharField(blank=True, choices=[('BRNBY', 'Burnaby Campus'), ('SURRY', 'Surrey Campus'), ('VANCR', 'Harbour Centre'), ('OFFST', 'Off-campus'), ('GNWC', 'Great Northern Way Campus'), ('METRO', 'Other Locations in Vancouver')], max_length=5, null=True),
        ),
        migrations.AlterField(
            model_name='location',
            name='category',
            field=models.CharField(blank=True, choices=[('STAFF', 'Staff'), ('FAC', 'Faculty'), ('PDOC', 'Post-Doc'), ('VISIT', 'Visitor'), ('SESS', 'Sessional'), ('LTERM', 'Limited-Term'), ('TA', 'TA'), ('GRAD', 'Grad Student'), ('URA', 'URA')], max_length=5, null=True),
        ),
        migrations.AlterField(
            model_name='location',
            name='infrastructure',
            field=models.CharField(blank=True, choices=[('WET', 'Wet Lab'), ('DRY', 'Dry Lab'), ('HPC', 'High-Performance Computing'), ('STD', 'Standard')], max_length=3, null=True),
        ),
        migrations.AlterField(
            model_name='location',
            name='own_or_lease',
            field=models.CharField(blank=True, choices=[('OWN', 'SFU Owned'), ('LEASE', 'Leased')], max_length=5, null=True, verbose_name='SFU Owned or Leased'),
        ),
        migrations.AlterField(
            model_name='location',
            name='room_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='space.RoomType'),
        ),
        migrations.AlterField(
            model_name='location',
            name='slug',
            field=autoslug.fields.AutoSlugField(editable=False, populate_from='autoslug', unique=True),
        ),
        migrations.AlterField(
            model_name='location',
            name='unit',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='coredata.Unit'),
        ),
        migrations.AlterField(
            model_name='roomtype',
            name='COU_code_description',
            field=models.CharField(help_text='e.g. "Academic Office Support Space"', max_length=256),
        ),
        migrations.AlterField(
            model_name='roomtype',
            name='COU_code_value',
            field=models.DecimalField(blank=True, decimal_places=1, help_text='e.g. 10.1', max_digits=4, null=True),
        ),
        migrations.AlterField(
            model_name='roomtype',
            name='code',
            field=models.CharField(help_text='e.g. "STOR_GEN"', max_length=50),
        ),
        migrations.AlterField(
            model_name='roomtype',
            name='long_description',
            field=models.CharField(help_text='e.g. "General Store"', max_length=256),
        ),
        migrations.AlterField(
            model_name='roomtype',
            name='slug',
            field=autoslug.fields.AutoSlugField(editable=False, populate_from='autoslug', unique=True),
        ),
        migrations.AlterField(
            model_name='roomtype',
            name='unit',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='coredata.Unit'),
        ),
    ]
