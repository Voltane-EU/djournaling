from datetime import datetime
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.fields import Field
from django.db.models.options import DEFAULT_NAMES as META_OPTIONS_DEFAULT_NAMES


class JournaledManager(models.Manager):
    pass


class JournaledQuerySet(models.QuerySet):
    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False):
        raise NotImplementedError

    def bulk_update(self, objs, fields, batch_size=None):
        raise NotImplementedError


class JournalModel(models.Model):
    def save(self, *args, **kwargs): # pylint:disable=arguments-differ
        # A existing journal entry may not be overriden
        if self.pk:
            raise ValidationError("Cannot update a journal entry")

        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        raise ValidationError("Cannot delete a journal entry")

    class Meta:
        abstract = True


class JournalMeta:
    unique_together = ('parent', 'timestamp',)
    indexes = (
        models.Index(fields=('parent', 'timestamp',)),
    )
    default_permissions = ()
    ordering = ['timestamp',]


class JournaledModelMixinMeta(ModelBase):
    def __new__(cls, name, bases, attrs, **kwargs):
        super_new = super().__new__

        attrs['objects'] = JournaledManager.from_queryset(JournaledQuerySet)()
        new_class = super_new(cls, name, bases, attrs, **kwargs)

        del attrs['objects']

        if not issubclass(new_class, models.Model):
            return new_class

        meta_attrs = {key: getattr(new_class._meta, key) for key in META_OPTIONS_DEFAULT_NAMES}
        meta_attrs.update(
            db_table=meta_attrs['db_table'] + '_journal'
        )
        NewJournalMeta = type(name + 'JournalMeta', (JournalMeta,), meta_attrs)

        journal_attrs = {
            '__module__': new_class.__module__,
            '__name__': name + 'Journal',
            '__qualname__': name + 'Journal',
            'Meta': NewJournalMeta,
            'id': models.BigAutoField(verbose_name='ID', primary_key=True, auto_created=True),
            'parent': models.ForeignKey(new_class, on_delete=models.CASCADE, related_name='journal_entries'),
            'timestamp': models.DateTimeField(auto_now_add=True, editable=False),
        }

        for att_name, att_value in attrs.items():
            if not isinstance(att_value, Field):
                continue

            journal_attrs[att_name] = att_value

        new_journal_class = super_new(cls, name + 'Journal', (JournalModel,) + bases, journal_attrs, **kwargs)
        new_journal_class._meta.journal = True
        new_journal_class._meta.journaled = False
        new_journal_class._meta.journaled_model = new_class

        new_class._meta.journal = False
        new_class._meta.journaled = True
        new_class._meta.journal_model = new_journal_class

        return new_class

    def __repr__(cls):
        if cls._meta.journal:
            return f"<Journal of {cls._meta.journaled_model}>"

        return super().__repr__()


class JournaledModelMixin(models.Model, metaclass=JournaledModelMixinMeta):
    def get_at_timestamp(self, timestamp: datetime):
        journal_entries = self.journal_entries.filter(timestamp__lte=timestamp).order_by('timestamp')
        return journal_entries.first()

    def save(self, *args, **kwargs): # pylint:disable=arguments-differ
        super().save(*args, **kwargs)

        if not self._meta.journaled:
            return

        self.journal_entries.create(**{
            field.attname: getattr(self, field.attname)
            for field in self._meta.fields if field != self._meta.pk
        })

    @property
    def update_datetime(self) -> datetime:
        return self.journal_entries.last().timestamp

    @property
    def create_datetime(self) -> datetime:
        return self.journal_entries.first().timestamp

    class Meta:
        abstract = True
