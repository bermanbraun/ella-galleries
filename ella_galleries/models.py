from collections import defaultdict
from django.db import models
from django.utils.translation import ugettext_lazy as _
from django.utils.datastructures import SortedDict
from django.core.cache import cache
from django.core.validators import validate_slug

from django.conf import settings

from app_data import AppDataField

from ella.core.models import Publishable
from ella.core.cache import cache_this, CachedForeignKey
from ella.core.custom_urls import resolver
from ella.core.views import get_templates_from_publishable
from ella.photos.models import Photo

ALLOW_PUBLISHABLE_SAVE_ON_PHOTO = getattr(settings, 'ALLOW_PUBLISHABLE_SAVE_ON_PHOTO', False)

def get_gallery_key(gallery):
    return 'galitems:%d' % gallery.id


class Gallery(Publishable):
    """
    Represents a Gallery of ``Photo`` objects.

    ``content`` use used to keep gallery description when rendering.
    """
    content = models.TextField(_('Content'), blank=True)
    created = models.DateTimeField(_('Created'), auto_now_add=True)

    class Meta:
        verbose_name = _('Gallery')
        verbose_name_plural = _('Galleries')

    @property
    def items(self):
        """
        Returns sorted dict of gallery items. Unique items slugs are used as keys.
        """
        if self.id:
            if not hasattr(self, '_items'):
                self._items = self._get_gallery_items()
            # we don't cache the .gallery property, so tack it on here to avoid
            # FK lookups
            for _, item in self._items.iteritems():
                item.gallery = self
            return self._items
        return SortedDict()

    @cache_this(get_gallery_key)
    def _get_gallery_items(self):
        slugs_count = defaultdict(int)
        slugs_unique = set()
        res = SortedDict()

        for item in self.galleryitem_set.order_by('order'):
            slug = item.get_item_slug()
            while slug in slugs_unique:
                slugs_count[slug] += 1
                slug = "%s%s" % (slug, slugs_count[slug])
            slugs_unique.add(slug)
            res[slug] = item
        return res

    def get_photo(self):
        if self.photo_id:
            return self.photo

        it = self.items
        if it:
            return it.values()[0].photo

        return None

    def save(self, **kwargs):
        if ALLOW_PUBLISHABLE_SAVE_ON_PHOTO:
            for key, item in self.items.iteritems():
                item.save_publishable_on_photo()

        super(Gallery, self).save(**kwargs)




class GalleryItem(models.Model):
    """
    One photo in a ``Gallery``. ``GalleryItem`` adds specific metadata for
    membership in gallery such as:

    ``order`` - position of photo in the gallery
    ``title`` - specific title in the gallery, can be blank
    ``text`` - description of photo in the gallery, can be blank too
    """
    slug = models.SlugField(_('Slug'), max_length=255, blank=True,
                            validators=[validate_slug], null=True)
    gallery = CachedForeignKey(Gallery, verbose_name=_("Parent gallery"))
    photo = CachedForeignKey(Photo, verbose_name=_("Photo"),
                             blank=True, null=True)
    order = models.IntegerField(_('Object order'))

    title = models.CharField(_('Title'), max_length=255, blank=True)
    text = models.TextField(blank=True)

    # generic JSON field to store app cpecific data
    app_data = AppDataField(default='{}', editable=False)

    class Meta:
        verbose_name = _('Gallery item')
        verbose_name_plural = _('Gallery items')

    def __unicode__(self):
        return u"%s %s %s" % (self.get_item_title(), _('in gallery'), self.gallery.title)

    def __get_slug(self):
        for slug, item in self.gallery.items.items():
            if item == self:
                return slug

    def get_slug(self):
        """
        Return a unique slug for given gallery, even if there are more objects
        with the same slug.
        """
        if not hasattr(self, '__slug'):
            self.__slug = self.__get_slug()
        return self.__slug

    def get_item_slug(self):
        return self.slug or (self.photo and self.photo.slug)

    def get_item_title(self):
        return self.title or (self.photo and self.photo.title)

    def get_absolute_url(self):
        if self.order == 0:
            return self.gallery.get_absolute_url()
        return resolver.reverse(self.gallery, 'gallery-item-detail', self.get_slug())

    def get_templates(self, name):
        return get_templates_from_publishable(name, self.gallery)

    def save_publishable_on_photo(self):
        if self.gallery.is_published() and self.photo:
            try:
                recent_pub_id = self.photo.app_data.recent_pub
                recent_pub = Publishable.objects.get(id=recent_pub_id)
                if recent_pub.publish_from < self.gallery.publish_from:
                    self.photo.app_data.recent_pub = self.gallery_id
            except:
                    self.photo.app_data["recent_pub"] =  self.gallery_id
            self.photo.save()

    def save(self):
        if ALLOW_PUBLISHABLE_SAVE_ON_PHOTO:
            self.save_publishable_on_photo();
        super(GalleryItem, self).save()



def invalidate_item_cache(instance, **kwargs):
    "Invalidate gallery item cache when a gallery item changes"
    key = get_gallery_key(instance.gallery)
    cache.delete(key)
models.signals.post_save.connect(invalidate_item_cache, sender=GalleryItem)
