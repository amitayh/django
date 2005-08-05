from django.utils import httpwrappers

class BaseHandler:
    def __init__(self):
        self._request_middleware = self._view_middleware = self._response_middleware = None

    def load_middleware(self):
        """
        Populate middleware lists from settings.MIDDLEWARE_CLASSES.

        Must be called after the environment is fixed (see __call__).
        """
        from django.conf import settings
        from django.core import exceptions
        self._request_middleware = []
        self._view_middleware = []
        self._response_middleware = []
        for middleware_path in settings.MIDDLEWARE_CLASSES:
            dot = middleware_path.rindex('.')
            mw_module, mw_classname = middleware_path[:dot], middleware_path[dot+1:]
            try:
                mod = __import__(mw_module, '', '', [''])
            except ImportError, e:
                raise exceptions.ImproperlyConfigured, 'Error importing middleware %s: "%s"' % (mw_module, e)
            try:
                mw_class = getattr(mod, mw_classname)
            except AttributeError:
                raise exceptions.ImproperlyConfigured, 'Middleware module "%s" does not define a "%s" class' % (mw_module, mw_classname)

            try:
                mw_instance = mw_class()
            except exceptions.MiddlewareNotUsed:
                continue

            if hasattr(mw_instance, 'process_request'):
                self._request_middleware.append(mw_instance.process_request)
            if hasattr(mw_instance, 'process_view'):
                self._view_middleware.append(mw_instance.process_view)
            if hasattr(mw_instance, 'process_response'):
                self._response_middleware.insert(0, mw_instance.process_response)

    def get_response(self, path, request):
        "Returns an HttpResponse object for the given HttpRequest"
        from django.core import db, exceptions, urlresolvers
        from django.core.mail import mail_admins
        from django.conf.settings import DEBUG, INTERNAL_IPS, ROOT_URLCONF

        # Apply request middleware
        for middleware_method in self._request_middleware:
            response = middleware_method(request)
            if response:
                return response

        resolver = urlresolvers.RegexURLResolver(r'^/', ROOT_URLCONF)
        try:
            callback, param_dict = resolver.resolve(path)
            # Apply view middleware
            for middleware_method in self._view_middleware:
                response = middleware_method(request, callback, param_dict)
                if response:
                    return response
            return callback(request, **param_dict)
        except exceptions.Http404:
            if DEBUG:
                return self.get_technical_error_response(is404=True)
            else:
                callback, param_dict = resolver.resolve404()
                return callback(request, **param_dict)
        except db.DatabaseError:
            db.db.rollback()
            if DEBUG:
                return self.get_technical_error_response()
            else:
                subject = 'Database error (%s IP)' % (request.META['REMOTE_ADDR'] in INTERNAL_IPS and 'internal' or 'EXTERNAL')
                message = "%s\n\n%s" % (self._get_traceback(), request)
                mail_admins(subject, message, fail_silently=True)
                return self.get_friendly_error_response(request, resolver)
        except exceptions.PermissionDenied:
            return httpwrappers.HttpResponseForbidden('<h1>Permission denied</h1>')
        except: # Handle everything else, including SuspiciousOperation, etc.
            if DEBUG:
                return self.get_technical_error_response()
            else:
                subject = 'Coding error (%s IP)' % (request.META['REMOTE_ADDR'] in INTERNAL_IPS and 'internal' or 'EXTERNAL')
                try:
                    request_repr = repr(request)
                except:
                    request_repr = "Request repr() unavailable"
                message = "%s\n\n%s" % (self._get_traceback(), request_repr)
                mail_admins(subject, message, fail_silently=True)
                return self.get_friendly_error_response(request, resolver)

    def get_friendly_error_response(self, request, resolver):
        """
        Returns an HttpResponse that displays a PUBLIC error message for a
        fundamental database or coding error.
        """
        from django.core import urlresolvers
        callback, param_dict = resolver.resolve500()
        return callback(request, **param_dict)

    def get_technical_error_response(self, is404=False):
        """
        Returns an HttpResponse that displays a TECHNICAL error message for a
        fundamental database or coding error.
        """
        error_string = "There's been an error:\n\n%s" % self._get_traceback()
        responseClass = is404 and httpwrappers.HttpResponseNotFound or httpwrappers.HttpResponseServerError
        return responseClass(error_string, mimetype='text/plain')

    def _get_traceback(self):
        "Helper function to return the traceback as a string"
        import sys, traceback
        return '\n'.join(traceback.format_exception(*sys.exc_info()))
