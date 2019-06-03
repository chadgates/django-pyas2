# Generated by Django 2.2.1 on 2019-06-02 19:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pyas2', '0003_partner_https_verify_ssl'),
    ]

    operations = [
        migrations.RenameField(
            model_name='publiccertificate',
            old_name='certificate_valid_from',
            new_name='valid_from',
        ),
        migrations.RenameField(
            model_name='publiccertificate',
            old_name='certificate_valid_to',
            new_name='valid_to',
        ),
        migrations.AddField(
            model_name='privatekey',
            name='valid_from',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='privatekey',
            name='valid_to',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]