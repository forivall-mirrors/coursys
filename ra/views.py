from django.urls import reverse
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponseRedirect, HttpResponse, StreamingHttpResponse
from django.contrib import messages
from django.db.models import Q
from django.utils.html import conditional_escape as escape
from ra.models import RAAppointment, RARequest, Project, Account, SemesterConfig, Program
from ra.forms import RAForm, RASearchForm, AccountForm, ProjectForm, RALetterForm, RABrowseForm, SemesterConfigForm, \
    LetterSelectForm, RAAppointmentAttachmentForm, ProgramForm, RARequestAdminForm, RARequestNoteForm, RARequestAdminAttachmentForm, \
    RARequestPAFForm, RARequestLetterForm, RARequestResearchAssistantForm, RARequestGraduateResearchAssistantForm, RARequestNonContinuingForm, \
    RARequestFundingSourceForm, RARequestSupportingForm, RARequestDatesForm, RARequestIntroForm, RARequestAdminPAFForm, RARequestScienceAliveForm
from grad.forms import possible_supervisors
from coredata.models import Person, Role, Semester, Unit
from coredata.queries import more_personal_info, SIMSProblem
from courselib.auth import requires_role, has_role, ForbiddenResponse, user_passes_test
from courselib.search import find_userid_or_emplid, get_query
from grad.models import GradStudent, Scholarship
from visas.models import Visa
from log.models import LogEntry
from dashboard.letters import ra_form, ra_paf, ra_science_alive, FASOfficialLetter, OfficialLetter, LetterContents
from django import forms
from django.db import transaction
from django.http import HttpResponse, HttpRequest
import csv

from django_datatables_view.base_datatable_view import BaseDatatableView
from haystack.query import SearchQuerySet

import json, datetime, urllib.request, urllib.parse, urllib.error

from django.shortcuts import render
from formtools.wizard.views import SessionWizardView
from django.conf import settings
from courselib.storage import UploadedFileStorage
from django.utils.decorators import method_decorator
import os

def _can_view_ras():
    """
    Allows access to funding admins, and supervisors of (any) RA.

    Request object gets .units and .is_supervisor set along the way.
    """
    def auth_test(request, **kwargs):
        supervisor = RAAppointment.objects.filter(hiring_faculty__userid=request.user.username).exists()
        request.is_supervisor = supervisor
        return has_role('FUND', request, **kwargs) or supervisor

    actual_decorator = user_passes_test(auth_test)
    return actual_decorator


def can_create():
    """
    Allows access to funding admins, and supervisors of (any) RA.

    Request object gets .units and .is_supervisor set along the way.
    """
    def auth_test(request, **kwargs):
        return has_role('FUND', request, **kwargs)

    actual_decorator = user_passes_test(auth_test)
    return actual_decorator

def _can_view_ra_requests():
    """
    Allows access to faculty members, and supervisors and authors of (any) RA.
    """
    def auth_test(request, **kwargs):
        supervisor = RARequest.objects.filter(supervisor__userid=request.user.username).exists()
        author = RARequest.objects.filter(author__userid=request.user.username).exists()
        request.is_supervisor = supervisor
        request.is_author = author
        return has_role('FAC', request, **kwargs) or has_role('FUND', request, **kwargs) or author or supervisor
    
    actual_decorator = user_passes_test(auth_test)
    return actual_decorator

#This is the search function that that returns a list of RA Appointments related to the query.
@requires_role("FUND")
def search(request, student_id=None):
    if student_id:
        student = get_object_or_404(Person, id=student_id)
    else:
        student = None
    if request.method == 'POST':
        form = RASearchForm(request.POST)
        if not form.is_valid():
            return HttpResponseRedirect(reverse('ra:found') + "?search=" + urllib.parse.quote_plus(form.data['search']))
        search = form.cleaned_data['search']
        # deal with people without active computing accounts
        if search.userid:
            userid = search.userid
        else:
            userid = search.emplid
        return HttpResponseRedirect(reverse('ra:student_appointments', kwargs={'userid': userid}))
    if student_id:
        form = RASearchForm(instance=student, initial={'student': student.userid})
    else:
        form = RASearchForm()
    context = {'form': form}
    return render(request, 'ra/search.html', context)

@requires_role("FUND")
def found(request):
    """
    View to handle the enter-search/press-enter behaviour in the autocomplete box
    """
    if 'search' not in request.GET:
        return ForbiddenResponse(request, 'must give search in query')
    search = request.GET['search']
    studentQuery = get_query(search, ['userid', 'emplid', 'first_name', 'last_name'])
    people = Person.objects.filter(studentQuery)[:200]
    for p in people:
        # decorate with RAAppointment count
        p.ras = RAAppointment.objects.filter(unit__in=request.units, person=p, deleted=False).count()

    context = {'people': people}
    return render(request, 'ra/found.html', context)

@requires_role("FUND")
def dashboard(request: HttpRequest) -> HttpResponse:
    reqs = RARequest.objects.filter(deleted=False, unit__in=request.units, complete=False)
    reqs_complete = RARequest.objects.filter(deleted=False, unit__in=request.units, complete=True)
    return render(request, 'ra/dashboard.html', {'reqs': reqs, 'reqs_complete': reqs_complete })

@_can_view_ra_requests()
def supervisor_dashboard(request: HttpRequest) -> HttpResponse:
    reqs = RARequest.objects.filter(Q(supervisor__userid=request.user.username) | Q(author__userid=request.user.username), deleted=False, complete=False)
    reqs_complete = RARequest.objects.filter(Q(supervisor__userid=request.user.username) | Q(author__userid=request.user.username), deleted=False, complete=True)
    return render(request, 'ra/supervisor_dashboard.html', {'reqs': reqs, 'reqs_complete': reqs_complete })

FORMS = [("intro", RARequestIntroForm),
         ("dates", RARequestDatesForm),
         ("funding_sources", RARequestFundingSourceForm),
         ("graduate_research_assistant", RARequestGraduateResearchAssistantForm),
         ("non_continuing", RARequestNonContinuingForm),
         ("research_assistant", RARequestResearchAssistantForm),
         ("supporting", RARequestSupportingForm)]

TEMPLATES = {"intro": "ra/new_request/intro.html",
             "dates": "ra/new_request/dates.html",
             "funding_sources": "ra/new_request/funding_sources.html",
             "graduate_research_assistant": "ra/new_request/graduate_research_assistant.html",
             "non_continuing": "ra/new_request/non_continuing.html",
             "research_assistant": "ra/new_request/research_assistant.html",
             "supporting": "ra/new_request/supporting.html"
             }

def _req_defaults(units, emplid=None):
    unit_choices = [(u.id, u.name) for u in units]
    return unit_choices

def check_gras(wizard):
    cleaned_data = wizard.get_cleaned_data_for_step('intro') or {'hiring_category': 'none'}
    return cleaned_data['hiring_category']=='GRAS'

def check_ra(wizard):
    cleaned_data = wizard.get_cleaned_data_for_step('intro') or {'hiring_category': 'none'}
    return cleaned_data['hiring_category']=='RA'
    
def check_nc(wizard):
    cleaned_data = wizard.get_cleaned_data_for_step('intro') or {'hiring_category': 'none'}
    return cleaned_data['hiring_category']=='NC'

# faculty members should not be able to reappoint any appointees that they are not authors or supervisors for
def _reappointment_req(request, ra_slug):
    req = None
    if has_role('FUND', request):
        req = get_object_or_404(RARequest, slug=ra_slug, deleted=False, unit__in=request.units)
    elif has_role('FAC', request):
        req = get_object_or_404(RARequest, Q(author__userid=request.user.username) | Q(supervisor__userid=request.user.username), slug=ra_slug, deleted=False)
    return req

@method_decorator(requires_role(["FUND", "FAC"]), name='dispatch')
class RANewRequestWizard(SessionWizardView):
    file_storage = UploadedFileStorage

    def get_template_names(self):
        return [TEMPLATES[self.steps.current]]
    
    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form=form, **kwargs)
        reappoint = 'ra_slug' in self.kwargs
        if self.steps.current == 'funding_sources':
            cleaned_data = self.get_cleaned_data_for_step('dates') or {}
            context.update({'start_date': cleaned_data['start_date'], 'end_date': cleaned_data['end_date']})
        if reappoint:
            ra_slug = self.kwargs['ra_slug']
            req = _reappointment_req(self.request, ra_slug)    
            context.update({'reappoint': True, 'slug': ra_slug, 'admin': has_role('FUND', self.request)})
        else: 
            context.update({'admin': has_role('FUND', self.request)})
        return context

    def get_form_initial(self, step):
        init = {}
        reappoint = 'ra_slug' in self.kwargs
        if reappoint:
            ra_slug = self.kwargs['ra_slug']
            req = _reappointment_req(self.request, ra_slug)        
        if step == 'intro' and reappoint:
            if req.nonstudent:
                init = {'supervisor': req.supervisor.emplid}
            if req.person:
                init = {'supervisor': req.supervisor.emplid, 'person': req.person.emplid}
        if step == 'funding_sources':
            cleaned_data = self.get_cleaned_data_for_step('dates') or {}
            # roll over start and end dates for validation, and initialize start dates of funding sources to overall start and end dates if not edit
            if reappoint:
                init = {'start_date': cleaned_data['start_date'], 'end_date': cleaned_data['end_date'],
                'fs1_start_date': req.fs1_start_date, 'fs2_start_date': req.fs2_start_date, 'fs3_start_date': req.fs3_start_date,
                'fs1_end_date': req.fs1_end_date, 'fs2_end_date': req.fs2_end_date, 'fs3_end_date': req.fs3_end_date}
            else:
                init = {'start_date': cleaned_data['start_date'], 'end_date': cleaned_data['end_date'],
                'fs1_start_date': cleaned_data['start_date'], 'fs2_start_date': cleaned_data['start_date'], 'fs3_start_date': cleaned_data['start_date'],
                'fs1_end_date': cleaned_data['end_date'], 'fs2_end_date': cleaned_data['end_date'], 'fs3_end_date': cleaned_data['end_date']}
        if step == 'non_continuing':
            cleaned_data = self.get_cleaned_data_for_step('dates') or {}
            init = {'pay_periods': cleaned_data['pay_periods'], 'backdated': cleaned_data['backdated']}
        if step == 'research_assistant':
            cleaned_data = self.get_cleaned_data_for_step('dates') or {}
            init = {'pay_periods': cleaned_data['pay_periods'], 'backdated': cleaned_data['backdated']}
        if step == 'graduate_research_assistant':
            cleaned_data = self.get_cleaned_data_for_step('dates') or {}
            init = {'pay_periods': cleaned_data['pay_periods'], 'backdated': cleaned_data['backdated']}
        return self.initial_dict.get(step, init)

    def get_form_instance(self, step):
        reappoint = 'ra_slug' in self.kwargs
        if reappoint:
            ra_slug = self.kwargs['ra_slug']
            req = _reappointment_req(self.request, ra_slug)
            # start and end dates on funding source form should be populated by whatever is entered on the dates form, regardless of edit/reappoint
            if step == "funding_sources":
                req.start_date = None
                req.end_date = None
            return req
        return self.instance_dict.get(step, None)

    def get_form(self, step=None, data=None, files=None):
        form = super(RANewRequestWizard, self).get_form(step, data, files)

        step = step or self.steps.current

        if step == 'intro': 
            unit_choices = _req_defaults(self.request.units)
            form.fields['unit'].choices = unit_choices

        return form

    def done(self, form_list, **kwargs):
        req = RARequest()
        for form in form_list:
            for field, value in form.cleaned_data.items():
                setattr(req, field, value)

        req.author = get_object_or_404(Person, userid=self.request.user.username)

        if req.hiring_category=="GRAS":
            req.ra_payment_method = None
            req.nc_payment_method = None
        if req.hiring_category=="RA":
            req.gras_payment_method = None
            req.nc_payment_method = None
        if req.hiring_category=="NC":
            req.gras_payment_method = None
            req.ra_payment_method = None

        req.build_letter_text()
        req.save()

        description = "Created RA Request %s." % req
        l = LogEntry(userid=self.request.user.username,
                        description=description,
                        related_object=req)
        l.save()

        messages.success(self.request, 'Created RA Request for ' + req.get_name())

        return HttpResponseRedirect(reverse('ra:view_request', kwargs={'ra_slug': req.slug}))

@method_decorator(requires_role("FUND"), name='dispatch')
class RAEditRequestWizard(SessionWizardView):
    file_storage = UploadedFileStorage

    def get_template_names(self):
        return [TEMPLATES[self.steps.current]]
    
    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form=form, **kwargs)
        if self.steps.current == 'funding_sources':
            cleaned_data = self.get_cleaned_data_for_step('dates') or {}
            context.update({'start_date': cleaned_data['start_date'], 'end_date': cleaned_data['end_date']})

        ra_slug = self.kwargs['ra_slug']
        req = get_object_or_404(RARequest, slug=ra_slug, deleted=False, unit__in=self.request.units)
        context.update({'edit': True, 'slug': ra_slug, 'name': req.get_name()})
        return context

    def get_form_initial(self, step):
        init = {}
        ra_slug = self.kwargs['ra_slug']
        req = get_object_or_404(RARequest, slug=ra_slug, deleted=False, unit__in=self.request.units)
        if step == 'intro':
            if req.nonstudent:
                init = {'supervisor': req.supervisor.emplid}
            if req.person:
                init = {'supervisor': req.supervisor.emplid, 'person': req.person.emplid}
        if step == 'funding_sources':
            cleaned_data = self.get_cleaned_data_for_step('dates') or {}
            # roll over start and end dates for validation, and initialize start dates of funding sources to overall start and end dates if not edit
            init = {'start_date': cleaned_data['start_date'], 'end_date': cleaned_data['end_date'],
            'fs1_start_date': req.fs1_start_date, 'fs2_start_date': req.fs2_start_date, 'fs3_start_date': req.fs3_start_date,
            'fs1_end_date': req.fs1_end_date, 'fs2_end_date': req.fs2_end_date, 'fs3_end_date': req.fs3_end_date}
        if step == 'non_continuing':
            cleaned_data = self.get_cleaned_data_for_step('dates') or {}
            init = {'pay_periods': cleaned_data['pay_periods'], 'backdated': req.backdated}
        if step == 'research_assistant':
            cleaned_data = self.get_cleaned_data_for_step('dates') or {}
            init = {'pay_periods': cleaned_data['pay_periods'], 'backdated': req.backdated}
        if step == 'graduate_research_assistant':
            cleaned_data = self.get_cleaned_data_for_step('dates') or {}
            init = {'pay_periods': cleaned_data['pay_periods'], 'backdated': req.backdated}
        return self.initial_dict.get(step, init)

    def get_form_instance(self, step):
        ra_slug = self.kwargs['ra_slug']
        req = get_object_or_404(RARequest, slug=ra_slug, deleted=False, unit__in=self.request.units)
        # start and end dates on funding source form should be populated whatever is entered on the dates form, regardless of edit/reappoint
        if step == "funding_sources":
            req.start_date = None
            req.end_date = None
        return req

    def get_form(self, step=None, data=None, files=None):
        form = super(RAEditRequestWizard, self).get_form(step, data, files)

        step = step or self.steps.current

        if step == 'intro': 
            unit_choices = _req_defaults(self.request.units)
            form.fields['unit'].choices = unit_choices

        return form

    def done(self, form_list, **kwargs):
        ra_slug = self.kwargs['ra_slug']
        req = get_object_or_404(RARequest, slug=ra_slug, deleted=False, unit__in=self.request.units)
        
        for form in form_list:
            for field, value in form.cleaned_data.items():
                setattr(req, field, value)

        req.last_updater = get_object_or_404(Person, userid=self.request.user.username)

        if req.hiring_category=="GRAS":
            req.ra_payment_method = None
            req.nc_payment_method = None
        if req.hiring_category=="RA":
            req.gras_payment_method = None
            req.nc_payment_method = None
        if req.hiring_category=="NC":
            req.gras_payment_method = None
            req.ra_payment_method = None

        req.save()

        description = "Edited RA Request %s." % req
    
        l = LogEntry(userid=self.request.user.username,
                        description=description,
                        related_object=req)
        l.save()

        messages.success(self.request, 'Edited RA Request for ' + req.get_name())

        return HttpResponseRedirect(reverse('ra:view_request', kwargs={'ra_slug': req.slug}))

# View RA Request
@_can_view_ra_requests()
def view_request(request: HttpRequest, ra_slug: str) -> HttpResponse:
    """
    View to view a RA request.
    """
    admin = has_role('FUND', request)

    if admin:
        req = get_object_or_404(RARequest, Q(unit__in=request.units), slug=ra_slug, deleted=False)
    else:
        req = get_object_or_404(RARequest, Q(author__userid=request.user.username) | Q(supervisor__userid=request.user.username), slug=ra_slug, deleted=False)

    person = req.person
    supervisor = req.supervisor
    author = req.author
    last_updater = req.last_updater
    # variables to help filter out unneccesary info to viewer
    research_assistant = (req.hiring_category=="RA")
    non_cont = (req.hiring_category=="NC")
    graduate_research_assistant = (req.hiring_category=="GRAS")
    gras_le = (graduate_research_assistant and req.gras_payment_method=="LS")
    gras_ls = (graduate_research_assistant and req.gras_payment_method=="LE")
    gras_bw = (graduate_research_assistant and req.gras_payment_method=="BW")
    ra_hourly = (research_assistant and req.ra_payment_method=="H")
    ra_bw = (research_assistant and req.ra_payment_method=="BW")
    nc_hourly = (non_cont and req.nc_payment_method=="H")
    nc_bw = (non_cont and req.nc_payment_method=="BW")

    adminform = RARequestAdminForm(instance=req)

    return render(request, 'ra/view_request.html',
        {'req': req, 'person': person, 'supervisor': supervisor, 'nonstudent': req.student=="N", 
         'author': author, 'research_assistant': research_assistant, 'non_cont': non_cont, 'no_id': req.nonstudent,
         'gras_le': gras_le, 'gras_ls': gras_ls, 'gras_bw': gras_bw, 'ra_hourly': ra_hourly, 'ra_bw': ra_bw,
         'nc_bw': nc_bw, 'nc_hourly': nc_hourly, 'thesis': req.mitacs=="N", 'adminform': adminform, 'admin': admin })

@requires_role("FUND")
def request_admin_update(request: HttpRequest, ra_slug: str) -> HttpResponse:
    req = get_object_or_404(RARequest, slug=ra_slug, deleted=False, unit__in=request.units)
    if request.method == 'POST':
        data = request.POST.copy()
        adminform = RARequestAdminForm(data, instance=req)
        if adminform.is_valid():
            req.complete = req.get_complete()
            req = adminform.save()
            l = LogEntry(userid=request.user.username,
                         description="Updated Progress for Request %s." % req,
                         related_object=req)
            l.save()
            messages.success(request, 'Updated Progress for RA Request for ' + req.get_name())
    
    return HttpResponseRedirect(reverse('ra:view_request', kwargs={'ra_slug': req.slug}))

@requires_role("FUND")
def delete_request(request: HttpRequest, ra_slug: str) -> HttpResponse:
    """
    View to delete a RA request.
    """
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    if request.method == 'POST':
        req.deleted = True
        req.save()
        messages.success(request, "Deleted RA Request." )
        l = LogEntry(userid=request.user.username,
              description="Deleted RA Request %s." % (str(req),),
              related_object=req)
        l.save()              
    
    return HttpResponseRedirect(reverse('ra:dashboard'))

@requires_role("FUND")
def edit_request_notes(request: HttpRequest, ra_slug: str) -> HttpResponse:
    """
    View to edit notes of an RA request.
    """
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    
    if request.method == 'POST':
        noteform = RARequestNoteForm(request.POST, instance=req)
        
        if noteform.is_valid():
            noteform.save()
            messages.success(request, "Edited Note for " + req.get_name())
            l = LogEntry(userid=request.user.username,
                description="Edited Note for RA Request %s" % (str(req),),
                related_object=req)
            l.save()              
            return HttpResponseRedirect(reverse('ra:view_request', kwargs={'ra_slug': req.slug}))
    else: 
        noteform = RARequestNoteForm(instance=req)
    return render(request, 'ra/edit_request_notes.html', {'noteform': noteform, 'req':req})

@requires_role("FUND")
def request_offer_letter(request: HttpRequest, ra_slug: str) -> HttpResponse:
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    response = HttpResponse(content_type="application/pdf")
    response['Content-Disposition'] = 'inline; filename="%s-letter.pdf"' % (req.slug)
    letter = FASOfficialLetter(response)
    contents = LetterContents(
        to_addr_lines=[req.get_name(), req.unit.name], 
        from_name_lines=[req.supervisor.letter_name(), req.unit.name],
        closing="Yours Truly", 
        signer=req.supervisor,
        cosigner_lines=[req.get_cosigner_line(), req.get_first_name() + " " + req.get_last_name()])
    contents.add_paragraphs(["Dear " + req.get_name()])
    contents.add_paragraphs(req.letter_paragraphs())
    letter.add_letter(contents)
    letter.write()
    return response

# for offer letters
@requires_role("FUND")
def request_offer_letter_update(request: HttpRequest, ra_slug: str) -> HttpResponse:
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)

    if request.method == 'POST':
        configform = RARequestLetterForm(request.POST, instance=req)
        if configform.is_valid():
            configform.save()
            messages.success(request, 'Updated Letter Text for ' + req.get_name())
            l = LogEntry(userid=request.user.username,
                description="Updated Letter Text for RA Request %s" % (str(req),),
                related_object=req)
            l.save()       
            return HttpResponseRedirect(reverse('ra:request_offer_letter_update', kwargs={'ra_slug': req.slug}))
    else:
        configform = RARequestLetterForm(instance=req)
        saform = RARequestScienceAliveForm()

    context = {'req': req, 'configform': configform, 'saform': saform}
    return render(request, 'ra/request_offer_letter.html', context) 

@requires_role("FUND")
def request_default_offer_letter(request: HttpRequest, ra_slug: str) -> HttpResponse:
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    if request.method == 'POST':
        req.build_letter_text()
        req.save()
        messages.success(request, 'Updated Letter Text for ' + req.get_name())
        l = LogEntry(userid=request.user.username,
              description="Updated Letter Text for RA Request (To Default) %s" % (str(req),),
              related_object=req)
        l.save()              

    return HttpResponseRedirect(reverse('ra:request_offer_letter_update', kwargs={'ra_slug': req.slug}))

@requires_role("FUND")
def request_science_alive(request: HttpRequest, ra_slug: str) -> HttpResponse:
    """
    Swtich appointment to science alive, or not science alive.
    Impacts offer letter generation.
    """
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    if request.method == 'POST':
        
        if req.hiring_category == "RA" or req.hiring_category=="NC":
            req.science_alive = not req.science_alive
        else: 
            req.science_alive = False
        
        req.save()
        messages.success(request, "Switched Science Alive Status for " + req.get_name())
        l = LogEntry(userid=request.user.username,
              description="Switched Science Alive Status for RA Request %s." % (str(req),),
              related_object=req)
        l.save()              
    
    return HttpResponseRedirect(reverse('ra:view_request', kwargs={'ra_slug': req.slug}))

@requires_role("FUND")
def request_science_alive_letter(request: HttpRequest, ra_slug: str) -> HttpResponse:
    req = get_object_or_404(RARequest, slug=ra_slug, deleted=False, unit__in=request.units)
    form = RARequestScienceAliveForm(request.POST)
    if form.is_valid():
        leter_type = form.cleaned_data['letter_type']
        config = ({'letter_type': form.cleaned_data['letter_type']})
        response = HttpResponse(content_type="application/pdf")
        response['Content-Disposition'] = 'inline; filename="%s.pdf"' % (req.slug)
        ra_science_alive(req, config, response)
        return response
    return HttpResponseRedirect(reverse('ra:request_offer_letter_update', kwargs={'ra_slug': req.slug}))


@requires_role("FUND")
def request_paf(request: HttpRequest, ra_slug: str) -> HttpResponse:
    req = get_object_or_404(RARequest, slug=ra_slug, deleted=False, unit__in=request.units)
    if request.method == 'POST':
        form = RARequestPAFForm(request.POST)
        if form.is_valid():
            appointment_type = form.cleaned_data['appointment_type']
            config = ({'appointment_type': form.cleaned_data['appointment_type']})
            response = HttpResponse(content_type="application/pdf")
            response['Content-Disposition'] = 'inline; filename="%s.pdf"' % (req.slug)
            ra_paf(req, config, response)
            return response
    else: 
        form = RARequestPAFForm()
        adminpafform = RARequestAdminPAFForm(instance=req)
    return render(request, 'ra/request_paf.html', {'form':form, 'adminpafform': adminpafform, 'req':req})


@requires_role("FUND")
def request_admin_paf_update(request: HttpRequest, ra_slug: str) -> HttpResponse:
    req = get_object_or_404(RARequest, slug=ra_slug, deleted=False, unit__in=request.units)
    if request.method == 'POST':
        data = request.POST.copy()
        if not req.fs2_option:
            data['fs2_object'] = ''
            data['fs2_program'] = ''    
        if not req.fs3_option:
            data['fs3_object'] = ''
            data['fs3_program'] = ''

        adminform = RARequestAdminPAFForm(data, instance=req)
        if adminform.is_valid():
            req = adminform.save()
            l = LogEntry(userid=request.user.username,
                         description="Updated PAF Config for Request %s." % req,
                         related_object=req)
            l.save()
            messages.success(request, 'Updated PAF Config for RA Request for ' + req.get_name())
    
    return HttpResponseRedirect(reverse('ra:request_paf', kwargs={'ra_slug': req.slug}))

@requires_role("FUND")
def view_request_attachment_1(request: HttpRequest, ra_slug: str) -> HttpResponse:
    """
    View to view the first attachment for an RA request.
    """
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    attachment = req.file_attachment_1
    filename = attachment.name.rsplit('/')[-1]
    resp = StreamingHttpResponse(attachment.chunks())
    resp['Content-Disposition'] = 'inline; filename="' + filename + '"'
    resp['Content-Length'] = attachment.size
    return resp

@requires_role("FUND")
def view_request_attachment_2(request: HttpRequest, ra_slug: str) -> HttpResponse:
    """
    View to view the second attachment for an RA request.
    """
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    attachment = req.file_attachment_2
    filename = attachment.name.rsplit('/')[-1]
    resp = StreamingHttpResponse(attachment.chunks())
    resp['Content-Disposition'] = 'inline; filename="' + filename + '"'
    resp['Content-Length'] = attachment.size
    return resp

@requires_role("FUND")
def download_request_attachment_1(request: HttpRequest, ra_slug: str) -> HttpResponse:
    """
    View to download the first attachment for an RA request.
    """
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    attachment = req.file_attachment_1
    filename = attachment.name.rsplit('/')[-1]
    resp = StreamingHttpResponse(attachment.chunks())
    resp['Content-Disposition'] = 'attachment; filename="' + filename + '"'
    resp['Content-Length'] = attachment.size
    return resp

@requires_role("FUND")
def download_request_attachment_2(request: HttpRequest, ra_slug: str) -> HttpResponse:
    """
    View to download the second attachment for an RA request.
    """
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    attachment = req.file_attachment_2
    filename = attachment.name.rsplit('/')[-1]
    resp = StreamingHttpResponse(attachment.chunks())
    resp['Content-Disposition'] = 'attachment; filename="' + filename + '"'
    resp['Content-Length'] = attachment.size
    return resp

@requires_role("FUND")
@transaction.atomic
def new_admin_attachment(request, ra_slug):
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    editor = get_object_or_404(Person, userid=request.user.username)

    form = RARequestAdminAttachmentForm()
    context = {"req": req,
               "attachment_form": form}

    if request.method == "POST":
        form = RARequestAdminAttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            attachment = form.save(commit=False)
            attachment.req = req
            attachment.created_by = editor
            upfile = request.FILES['contents']
            filetype = upfile.content_type
            if upfile.charset:
                filetype += "; charset=" + upfile.charset
            attachment.mediatype = filetype
            attachment.save()
            messages.add_message(request, messages.SUCCESS, 'Admin attachment added.')
            l = LogEntry(userid=request.user.username, description="Added admin attachment %s" % attachment, related_object=attachment)
            return HttpResponseRedirect(reverse('ra:view_request', kwargs={'ra_slug': req.slug}))
        else:
            context.update({"attachment_form": form})

    return render(request, 'ra/new_request_attachment.html', context)

@requires_role("FUND")
def view_admin_attachment(request, ra_slug, attach_slug):
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    attachment = get_object_or_404(req.attachments.all(), slug=attach_slug)
    filename = attachment.contents.name.rsplit('/')[-1]
    resp = StreamingHttpResponse(attachment.contents.chunks(), content_type=attachment.mediatype)
    resp['Content-Disposition'] = 'inline; filename="' + filename + '"'
    resp['Content-Length'] = attachment.contents.size
    return resp

@requires_role("FUND")
def download_admin_attachment(request, ra_slug, attach_slug):
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    attachment = get_object_or_404(req.attachments.all(), slug=attach_slug)
    filename = attachment.contents.name.rsplit('/')[-1]
    resp = StreamingHttpResponse(attachment.contents.chunks(), content_type=attachment.mediatype)
    resp['Content-Disposition'] = 'attachment; filename="' + filename + '"'
    resp['Content-Length'] = attachment.contents.size
    return resp

@requires_role("FUND")
def delete_admin_attachment(request, ra_slug, attach_slug):
    req = get_object_or_404(RARequest, slug=ra_slug, unit__in=request.units)
    attachment = get_object_or_404(req.attachments.all(), slug=attach_slug)
    attachment.hide()
    messages.add_message(request,
                         messages.SUCCESS,
                         'Admin attachment deleted.'
                         )
    l = LogEntry(userid=request.user.username, description="Hid admin attachment %s" % attachment, related_object=attachment)
    l.save()
    return HttpResponseRedirect(reverse('ra:view_request', kwargs={'ra_slug': req.slug}))

#This is an index of all RA Appointments belonging to a given person.
@requires_role("FUND")
def student_appointments(request, userid):
    student = get_object_or_404(Person, find_userid_or_emplid(userid))
    appointments = RAAppointment.objects.filter(person=student, unit__in=request.units, deleted=False).order_by("-created_at")
    grads = GradStudent.objects.filter(person=student, program__unit__in=request.units)
    context = {'appointments': appointments, 'student': student,
               'grads': grads}
    return render(request, 'ra/student_appointments.html', context)

def _appointment_defaults(units, emplid=None):
    hiring_faculty_choices = possible_supervisors(units)
    unit_choices = [(u.id, u.name) for u in units]
    project_choices = [(p.id, str(p)) for p in Project.objects.filter(unit__in=units, hidden=False)]
    account_choices = [(a.id, str(a)) for a in Account.objects.filter(unit__in=units, hidden=False)]
    scholarship_choices = [("", '\u2014')]
    if emplid:
        for s in Scholarship.objects.filter(student__person__emplid=emplid):
            scholarship_choices.append((s.pk, s.scholarship_type.unit.label + ": " + s.scholarship_type.name + " (" + s.start_semester.name + " to " + s.end_semester.name + ")"))
    program_choices = [('', "00000, None")] + [(p.id, str(p)) for p in Program.objects.visible_by_unit(units).order_by('program_number')]
    return (scholarship_choices, hiring_faculty_choices, unit_choices, project_choices, account_choices,
            program_choices)

#New RA Appointment
@requires_role("FUND")
def new(request):
    scholarship_choices, hiring_faculty_choices, unit_choices, project_choices, account_choices, program_choices = \
        _appointment_defaults(request.units)
    if request.method == 'POST':
        data = request.POST.copy()
        if data['pay_frequency'] == 'L':
            # force legal values into the non-submitted (and don't-care) fields for lump sum pay
            data['biweekly_pay'] = 1
            data['hourly_pay'] = 1
            data['hours'] = 1
            data['pay_periods'] = 1

        raform = RAForm(data)
        raform.fields['hiring_faculty'].choices = hiring_faculty_choices
        raform.fields['unit'].choices = unit_choices
        raform.fields['project'].choices = project_choices
        raform.fields['account'].choices = account_choices
        raform.fields['program'].choices = program_choices

        if raform.is_valid():
            userid = raform.cleaned_data['person'].userid_or_emplid()
            appointment = raform.save(commit=False)
            appointment.set_use_hourly(raform.cleaned_data['use_hourly'])
            appointment.save()
            l = LogEntry(userid=request.user.username,
                         description="Added RA appointment %s." % appointment,
                         related_object=appointment)
            l.save()
            messages.success(request, 'Created RA Appointment for ' + appointment.person.name())
            return HttpResponseRedirect(reverse('ra:student_appointments', kwargs=({'userid': userid})))
    else:
        semester = Semester.next_starting()
        semesterconfig = SemesterConfig.get_config(request.units, semester)
        raform = RAForm(initial={'start_date': semesterconfig.start_date(), 'end_date': semesterconfig.end_date(), 'hours': 80 })
        raform.fields['scholarship'].choices = scholarship_choices
        raform.fields['hiring_faculty'].choices = hiring_faculty_choices
        raform.fields['unit'].choices = unit_choices
        raform.fields['project'].choices = project_choices
        raform.fields['account'].choices = account_choices
        raform.fields['program'].choices = program_choices
    return render(request, 'ra/new.html', { 'raform': raform })

#New RA Appointment with student pre-filled.
@requires_role("FUND")
def new_student(request, userid):
    person = get_object_or_404(Person, find_userid_or_emplid(userid))
    semester = Semester.next_starting()
    semesterconfig = SemesterConfig.get_config(request.units, semester)
    student = get_object_or_404(Person, find_userid_or_emplid(userid))
    initial = {'person': student.emplid, 'start_date': semesterconfig.start_date(), 'end_date': semesterconfig.end_date(), 'hours': 80 }
    scholarship_choices, hiring_faculty_choices, unit_choices, project_choices, account_choices, program_choices = \
        _appointment_defaults(request.units, emplid=student.emplid)
    gss = GradStudent.objects.filter(person=student)
    if gss:
        gradstudent = gss[0]
        initial['sin'] = gradstudent.person.sin()
    
    raform = RAForm(initial=initial)
    raform.fields['person'] = forms.CharField(widget=forms.HiddenInput())
    raform.fields['scholarship'].choices = scholarship_choices
    raform.fields['hiring_faculty'].choices = hiring_faculty_choices
    raform.fields['unit'].choices = unit_choices
    raform.fields['project'].choices = project_choices
    raform.fields['account'].choices = account_choices
    raform.fields['program'].choices = program_choices
    return render(request, 'ra/new.html', { 'raform': raform, 'person': person })

#Edit RA Appointment
@requires_role("FUND")
def edit(request, ra_slug):
    appointment = get_object_or_404(RAAppointment, slug=ra_slug, deleted=False, unit__in=request.units)
    scholarship_choices, hiring_faculty_choices, unit_choices, project_choices, account_choices, program_choices = \
        _appointment_defaults(request.units, emplid=appointment.person.emplid)
    if request.method == 'POST':
        data = request.POST.copy()
        if data['pay_frequency'] == 'L':
            # force legal values into the non-submitted (and don't-care) fields for lump sum pay
            data['biweekly_pay'] = 1
            data['hourly_pay'] = 1
            data['hours'] = 1
            data['pay_periods'] = 1
        
        raform = RAForm(data, instance=appointment)
        if raform.is_valid():
            userid = raform.cleaned_data['person'].userid
            appointment = raform.save(commit=False)
            appointment.set_use_hourly(raform.cleaned_data['use_hourly'])
            appointment.save()
            l = LogEntry(userid=request.user.username,
                         description="Edited RA appointment %s." % appointment,
                         related_object=appointment)
            l.save()
            messages.success(request, 'Updated RA Appointment for ' + appointment.person.first_name + " " + appointment.person.last_name)
            return HttpResponseRedirect(reverse('ra:student_appointments', kwargs=({'userid': userid})))
    else:
        #The initial value needs to be the person's emplid in the form. Django defaults to the pk, which is not human readable.
        raform = RAForm(instance=appointment, initial={'person': appointment.person.emplid, 'use_hourly': appointment.use_hourly()})
        #As in the new method, choices are restricted to relevant options.
        raform.fields['person'] = forms.CharField(widget=forms.HiddenInput())
        raform.fields['hiring_faculty'].choices = hiring_faculty_choices
        raform.fields['scholarship'].choices = scholarship_choices
        raform.fields['unit'].choices = unit_choices
        raform.fields['project'].choices = project_choices
        raform.fields['account'].choices = account_choices
        raform.fields['program'].choices = program_choices
    return render(request, 'ra/edit.html', { 'raform': raform, 'appointment': appointment, 'person': appointment.person })

#Quick Reappoint, The difference between this and edit is that the reappointment box is automatically checked, and date information is filled out as if a new appointment is being created.
#Since all reappointments will be new appointments, no post method is present, rather the new appointment template is rendered with the existing data which will call the new method above when posting.
@requires_role("FUND")
def reappoint(request, ra_slug):
    appointment = get_object_or_404(RAAppointment, slug=ra_slug, deleted=False, unit__in=request.units)
    semester = Semester.next_starting()
    semesterconfig = SemesterConfig.get_config(request.units, semester)
    raform = RAForm(instance=appointment, initial={'person': appointment.person.emplid, 'reappointment': True,
                    'start_date': semesterconfig.start_date(), 'end_date': semesterconfig.end_date(), 'hours': 80,
                    'use_hourly': appointment.use_hourly() })
    scholarship_choices, hiring_faculty_choices, unit_choices, project_choices, account_choices, program_choices = \
        _appointment_defaults(request.units, emplid=appointment.person.emplid)
    raform.fields['hiring_faculty'].choices = hiring_faculty_choices
    raform.fields['scholarship'].choices = scholarship_choices
    raform.fields['unit'].choices = unit_choices
    raform.fields['project'].choices = project_choices
    raform.fields['account'].choices = account_choices
    raform.fields['program'].choices = program_choices
    return render(request, 'ra/new.html', { 'raform': raform, 'appointment': appointment })


@requires_role("FUND")
def edit_letter(request, ra_slug):
    appointment = get_object_or_404(RAAppointment, slug=ra_slug, deleted=False, unit__in=request.units)

    if request.method == 'POST':
        form = RALetterForm(request.POST, instance=appointment)
        if form.is_valid():
            form.save()
            messages.success(request, 'Updated RA Letter Text for ' + appointment.person.first_name + " " + appointment.person.last_name)
            return HttpResponseRedirect(reverse('ra:student_appointments', kwargs=({'userid': appointment.person.userid})))
    else:
        if not appointment.offer_letter_text:
            letter_choices = RAAppointment.letter_choices(request.units)
            if len(letter_choices) == 1: # why make them select from one?
                appointment.build_letter_text(letter_choices[0][0])
            else:
                return HttpResponseRedirect(reverse('ra:select_letter', kwargs=({'ra_slug': ra_slug})))
        form = RALetterForm(instance=appointment)
    
    context = {'appointment': appointment, 'form': form}
    return render(request, 'ra/edit_letter.html', context)

# If we don't have an appointment letter yet, pick one.
@requires_role("FUND")
def select_letter(request, ra_slug, print_only=None):
    appointment = get_object_or_404(RAAppointment, slug=ra_slug, deleted=False, unit__in=request.units)
    # Forcing sorting of the letter choices so the Standard template is first.
    letter_choices = sorted(RAAppointment.letter_choices(request.units))
    if request.method == 'POST':
        filled_form = LetterSelectForm(data=request.POST, choices=letter_choices)
        if filled_form.is_valid():
            appointment.build_letter_text(filled_form.cleaned_data['letter_choice'])
        if print_only == 'print':
            return HttpResponseRedirect(reverse('ra:letter', kwargs=({'ra_slug': ra_slug})))
        else:
            return HttpResponseRedirect(reverse('ra:edit_letter', kwargs=({'ra_slug': ra_slug})))

    else:
        new_form = LetterSelectForm(choices=letter_choices)
        context = {'form': new_form, 'ra_slug': ra_slug, 'print_only': print_only}
        return render(request, 'ra/select_letter.html', context)

#View RA Appointment
@_can_view_ras()
def view(request, ra_slug):
    appointment = get_object_or_404(RAAppointment,
        Q(unit__in=request.units) | Q(hiring_faculty__userid=request.user.username),
        slug=ra_slug, deleted=False)
    student = appointment.person
    return render(request, 'ra/view.html',
        {'appointment': appointment, 'student': student, 'supervisor_only': not request.units})

#View RA Appointment Form (PDF)
@requires_role("FUND")
def form(request, ra_slug):
    appointment = get_object_or_404(RAAppointment, slug=ra_slug, deleted=False, unit__in=request.units)
    response = HttpResponse(content_type="application/pdf")
    response['Content-Disposition'] = 'inline; filename="%s.pdf"' % (appointment.slug)
    ra_form(appointment, response)
    return response

@requires_role("FUND")
def letter(request, ra_slug):
    appointment = get_object_or_404(RAAppointment, slug=ra_slug, deleted=False, unit__in=request.units)
    if not appointment.offer_letter_text:
        letter_choices = RAAppointment.letter_choices(request.units)
        if len(letter_choices) == 1:  # why make them select from one?
            appointment.build_letter_text(letter_choices[0][0])
        else:
            return HttpResponseRedirect(reverse('ra:select_letter', kwargs=({'ra_slug': ra_slug, 'print_only': 'print'})))
    response = HttpResponse(content_type="application/pdf")
    response['Content-Disposition'] = 'inline; filename="%s-letter.pdf"' % (appointment.slug)
    letter = OfficialLetter(response, unit=appointment.unit)
    contents = LetterContents(
        to_addr_lines=[appointment.person.name(), 'c/o '+appointment.unit.name], 
        from_name_lines=[appointment.hiring_faculty.letter_name(), appointment.unit.name],
        closing="Yours Truly", 
        signer=appointment.hiring_faculty,
        cosigner_lines=['I agree to the conditions of employment', appointment.person.first_name + " " + appointment.person.last_name])
    contents.add_paragraphs(["Dear " + appointment.person.get_title() + ' ' + appointment.person.last_name])
    contents.add_paragraphs(appointment.letter_paragraphs())
    letter.add_letter(contents)
    letter.write()
    return response

@requires_role("FUND")
def delete_ra(request, ra_slug):
    appointment = get_object_or_404(RAAppointment, slug=ra_slug, unit__in=request.units)
    if request.method == 'POST':
        appointment.deleted = True
        appointment.save()
        messages.success(request, "Deleted RA appointment." )
        l = LogEntry(userid=request.user.username,
              description="Deleted RA appointment %s." % (str(appointment),),
              related_object=appointment)
        l.save()              
    
    return HttpResponseRedirect(reverse('ra:student_appointments', kwargs={'userid': appointment.person.emplid}))

# Methods relating to Account creation. These are all straight forward.
@requires_role(["FUND", "TAAD", "GRAD"])
def new_account(request):
    accountform = AccountForm(request.POST or None)
    #This restricts a user to only creating account for a unit to which they belong.
    accountform.fields['unit'].choices = [(u.id, u.name) for u in request.units]
    if request.method == 'POST':
        if accountform.is_valid():
            account = accountform.save()
            messages.success(request, 'Created account ' + str(account.account_number))
            return HttpResponseRedirect(reverse('ra:accounts_index'))
    return render(request, 'ra/new_account.html', {'accountform': accountform})

@requires_role("FUND")
def accounts_index(request):
    accounts = Account.objects.filter(unit__in=request.units, hidden=False).order_by("account_number")
    return render(request, 'ra/accounts_index.html', {'accounts': accounts})

@requires_role("FUND")
def edit_account(request, account_slug):
    account = get_object_or_404(Account, slug=account_slug, unit__in=request.units)
    if request.method == 'POST':
        accountform = AccountForm(request.POST, instance=account)
        if accountform.is_valid():
            accountform.save()
            messages.success(request, 'Updated account ' + str(account.account_number))
            return HttpResponseRedirect(reverse('ra:accounts_index'))
    else:
        accountform = AccountForm(instance=account)
        accountform.fields['unit'].choices = [(u.id, u.name) for u in request.units]
    return render(request, 'ra/edit_account.html', {'accountform': accountform, 'account': account})

@requires_role("FUND")
def remove_account(request, account_slug):
    account = get_object_or_404(Account, slug=account_slug, unit__in=request.units)
    account.delete()
    messages.success(request, "Removed account %s." % str(account.account_number))
    l = LogEntry(userid=request.user.username,
          description="Removed account %s" % (str(account.account_number)),
          related_object=account)
    l.save()              
    
    return HttpResponseRedirect(reverse('ra:accounts_index'))

#Project methods. Also straight forward.
@requires_role("FUND")
def new_project(request):
    projectform = ProjectForm(request.POST or None)
    #Again, the user should only be able to create projects for units that they belong to.
    projectform.fields['unit'].choices = [(u.id, u.name) for u in request.units]
    if request.method == 'POST':
        if projectform.is_valid():
            project = projectform.save()
            messages.success(request, 'Created project ' + str(project.project_number))
            return HttpResponseRedirect(reverse('ra:projects_index'))
    return render(request, 'ra/new_project.html', {'projectform': projectform})

@requires_role("FUND")
def projects_index(request):
    depts = Role.objects_fresh.filter(person__userid=request.user.username, role='FUND').values('unit_id')
    projects = Project.objects.filter(unit__id__in=depts, hidden=False).order_by("project_number")
    return render(request, 'ra/projects_index.html', {'projects': projects})

@requires_role("FUND")
def edit_project(request, project_slug):
    project = get_object_or_404(Project, slug=project_slug, unit__in=request.units)
    if request.method == 'POST':
        projectform = ProjectForm(request.POST, instance=project)
        if projectform.is_valid():
            projectform.save()
            messages.success(request, 'Updated project ' + str(project.project_number))
            return HttpResponseRedirect(reverse('ra:projects_index'))
    else:
        projectform = ProjectForm(instance=project)
        projectform.fields['unit'].choices = [(u.id, u.name) for u in request.units]
    return render(request, 'ra/edit_project.html', {'projectform': projectform, 'project': project})

@requires_role("FUND")
def remove_project(request, project_slug):
    project = get_object_or_404(Project, slug=project_slug, unit__in=request.units)
    project.delete()
    messages.success(request, "Removed project %s." % str(project.project_number))
    l = LogEntry(userid=request.user.username,
          description="Removed project %s" % (str(project.project_number)),
          related_object=project)
    l.save()              
    
    return HttpResponseRedirect(reverse('ra:projects_index'))

@requires_role("FUND")
def semester_config(request, semester_name=None):
    if semester_name:
        semester = get_object_or_404(Semester, name=semester_name)
    else:
        semester = Semester.next_starting()

    unit_choices = [(u.id, u.name) for u in request.units]
    if request.method == 'POST':
        form = SemesterConfigForm(request.POST)
        form.fields['unit'].choices = unit_choices
        if form.is_valid():
            config = SemesterConfig.get_config(units=[form.cleaned_data['unit']], semester=semester)
            config.set_start_date(form.cleaned_data['start_date'])
            config.set_end_date(form.cleaned_data['end_date'])
            config.save()
            messages.success(request, 'Updated semester configuration for %s.' % (semester.name))
            return HttpResponseRedirect(reverse('ra:search'))
    else:
        config = SemesterConfig.get_config(units=request.units, semester=semester)
        form = SemesterConfigForm(initial={'start_date': config.start_date(), 'end_date': config.end_date()})
        form.fields['unit'].choices = unit_choices

    return render(request, 'ra/semester_config.html', {'semester': semester, 'form': form})



@requires_role("FUND")
def search_scholarships_by_student(request, student_id):
    #check permissions
    roles = Role.all_roles(request.user.username)
    allowed = set(['FUND'])
    if not (roles & allowed):
        return ForbiddenResponse(request, "Not permitted to search scholarships by student.")
    scholarships = Scholarship.objects.filter(student__person__emplid=student_id)
    response = HttpResponse(content_type="application/json")
    data = [{'value': s.pk, 'display': s.scholarship_type.unit.label + ": " + s.scholarship_type.name + " (" + s.start_semester.name + " to " + s.end_semester.name + ")"}  for s in scholarships]
    json.dump(data, response, indent=1)
    return response

@_can_view_ras()
def browse(request):
    if 'tabledata' in request.GET:
        return RADataJson.as_view()(request)

    form = RABrowseForm()
    context = {'form': form, 'supervisor_only': not request.units}
    return render(request, 'ra/browse.html', context)


class RADataJson(BaseDatatableView):
    model = RAAppointment
    columns = ['person', 'hiring_faculty', 'unit', 'project', 'account', 'start_date', 'end_date', 'lump_sum_pay']
    order_columns = [
        ['person__last_name', 'person__first_name'],
        ['hiring_faculty__last_name', 'hiring_faculty__first_name'],
        'unit__label',
        'project__project_number',
        'account__account_number',
        'start_date',
        'end_date',
        'lump_sum_pay',
    ]
    max_display_length = 500

    def get_initial_queryset(self):
        qs = super(RADataJson, self).get_initial_queryset()
        # do some select related because we'll need them for display later
        qs = qs.select_related('person', 'hiring_faculty', 'unit')
        return qs

    def filter_queryset(self, qs):
        GET = self.request.GET

        # limit to those visible to this user
        qs = qs.filter(
            Q(unit__in=self.request.units)
            | Q(hiring_faculty__userid=self.request.user.username)
        )
        qs = qs.exclude(deleted=True)

        # "current" contracts filter
        if 'current' in GET and GET['current'] == 'yes':
            today = datetime.date.today()
            slack = 14 # number of days to fudge the start/end
            qs = qs.filter(start_date__lte=today + datetime.timedelta(days=slack),
                           end_date__gte=today - datetime.timedelta(days=slack))

        # search box
        srch = GET.get('sSearch', None)
        if srch:
            # get RA set from haystack, and use it to limit our query.
            ra_qs = SearchQuerySet().models(RAAppointment).filter(text__fuzzy=srch)[:500]
            ra_qs = [r for r in ra_qs if r is not None]
            if ra_qs:
                # ignore very low scores: elasticsearch grabs too much sometimes
                max_score = max(r.score for r in ra_qs)
                ra_pks = (r.pk for r in ra_qs if r.score > max_score/5)
                qs = qs.filter(pk__in=ra_pks)
            else:
                qs = qs.none()

        return qs

    def render_column(self, ra, column):
        if column == 'lump_sum_pay':
            return "${:,}".format(ra.lump_sum_pay)
        elif column == 'person':
            url = ra.get_absolute_url()
            name = ra.person.sortname()
            if ra.has_attachments():
                extra_string = '&nbsp; <i class="fa fa-paperclip" title="Attachment(s)"></i>'
            else:
                extra_string = ''
            return '<a href="%s">%s%s</a>' % (escape(url), escape(name), extra_string)
        elif column == 'unit':
            return ra.unit.label

        return str(getattr(ra, column))


@_can_view_ras()
def download_ras(request, current=True):
    ras = RAAppointment.objects.filter(Q(unit__in=request.units)
                                       | Q(hiring_faculty__userid=request.user.username))\
        .select_related('person', 'hiring_faculty', 'unit', 'project', 'account').exclude(deleted=True)
    if current:
        today = datetime.date.today()
        slack = 14  # number of days to fudge the start/end
        ras = ras.filter(start_date__lte=today + datetime.timedelta(days=slack),
                         end_date__gte=today - datetime.timedelta(days=slack))
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'inline; filename="ras-%s-%s.csv"' % (datetime.datetime.now().strftime('%Y%m%d'),
                                                                            'current' if current else 'all')
    writer = csv.writer(response)
    writer.writerow(['Name', 'ID', 'Hiring Faculty', 'Unit', 'Project', 'Account', 'Start Date', 'End Date', 'Amount'])
    for ra in ras:
        writer.writerow([ra.person.sortname(), ra.person.emplid, ra.hiring_faculty.sortname(), ra.unit.label, ra.project, ra.account, ra.start_date, ra.end_date, ra.lump_sum_pay])
    return response


def pay_periods(request):
    """
    Calculate number of pay periods between contract start and end dates.
    i.e. number of work days in period / 10
    
    I swear this was easier that doing it in JS, okay?
    """
    day = datetime.timedelta(days=1)
    week = datetime.timedelta(days=7)
    if 'start' not in request.GET or 'end' not in request.GET:
        result = ''
    else:
        st = request.GET['start']
        en = request.GET['end']
        try:
            st = datetime.datetime.strptime(st, "%Y-%m-%d").date()
            en = datetime.datetime.strptime(en, "%Y-%m-%d").date()
        except ValueError:
            result = ''
        else:
            # move start/end into Mon-Fri work week
            if st.weekday() == 5:
                st += 2*day
            elif st.weekday() == 6:
                st += day
            if en.weekday() == 5:
                en -= day
            elif en.weekday() == 6:
                en -= 2*day

            # number of full weeks (until sameday: last same weekday before end date)
            weeks = ((en-st)/7).days
            sameday = st + weeks*week
            assert sameday <= en < sameday + week
            
            # number of days remaining
            days = (en - sameday).days
            if sameday.weekday() > en.weekday():
                # don't count weekend days in between
                days -= 2
            
            days += 1 # count both start and end days
            result = "%.1f" % ((weeks*5 + days)/10.0)
    
    return HttpResponse(result, content_type='text/plain;charset=utf-8')


@requires_role("FUND")
def person_info(request):
    """
    Get more info about this person, for AJAX updates on new RA form
    """
    result = {'programs': []}
    emplid = request.GET.get('emplid', None)
    if not emplid or not emplid.isdigit() or len(emplid) != 9:
        pass
    else:
        programs = []
        
        # GradPrograms
        emplid = request.GET['emplid']
        grads = GradStudent.objects.filter(person__emplid=emplid, program__unit__in=request.units)
        for gs in grads:
            pdata = {
                     'program': gs.program.label,
                     'unit': gs.program.unit.name,
                     'status': gs.get_current_status_display(),
                     }
            programs.append(pdata)

        result['programs'] = programs
        
        # other SIMS info
        try:
            otherinfo = more_personal_info(emplid, needed=['citizen', 'visa'])
            result.update(otherinfo)
        except SIMSProblem as e:
            result['error'] = str(e)

    return HttpResponse(json.dumps(result), content_type='application/json;charset=utf-8')


@requires_role("FUND")
def person_visas(request):
    """
    Get info on this person's current visas, for info in the new RA appointment form.
    """
    result = {'visas': []}
    emplid = request.GET.get('emplid', None)
    if not emplid or not emplid.isdigit() or len(emplid) != 9:
        pass
    else:
        visas = []
        personvisas = Visa.objects.visible().filter(person__emplid=emplid, unit__in=request.units)
        for v in personvisas:
            if v.is_current():
                data = {
                    'start': v.start_date.isoformat(),
                    'status': v.status,
                }
                visas.append(data)
        result['visas'] = visas
    return HttpResponse(json.dumps(result), content_type='application/json;charset=utf-8')


@requires_role("FUND")
@transaction.atomic
def new_attachment(request, ra_slug):
    appointment = get_object_or_404(RAAppointment, slug=ra_slug, unit__in=request.units)
    editor = get_object_or_404(Person, userid=request.user.username)

    form = RAAppointmentAttachmentForm()
    context = {"appointment": appointment,
               "attachment_form": form}

    if request.method == "POST":
        form = RAAppointmentAttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            attachment = form.save(commit=False)
            attachment.appointment = appointment
            attachment.created_by = editor
            upfile = request.FILES['contents']
            filetype = upfile.content_type
            if upfile.charset:
                filetype += "; charset=" + upfile.charset
            attachment.mediatype = filetype
            attachment.save()
            return HttpResponseRedirect(reverse('ra:view', kwargs={'ra_slug': appointment.slug}))
        else:
            context.update({"attachment_form": form})

    return render(request, 'ra/appointment_attachment_form.html', context)


@requires_role("FUND")
def view_attachment(request, ra_slug, attach_slug):
    appointment = get_object_or_404(RAAppointment, slug=ra_slug, unit__in=request.units)
    attachment = get_object_or_404(appointment.attachments.all(), slug=attach_slug)
    filename = attachment.contents.name.rsplit('/')[-1]
    resp = StreamingHttpResponse(attachment.contents.chunks(), content_type=attachment.mediatype)
    resp['Content-Disposition'] = 'inline; filename="' + filename + '"'
    resp['Content-Length'] = attachment.contents.size
    return resp


@requires_role("FUND")
def download_attachment(request, ra_slug, attach_slug):
    appointment = get_object_or_404(RAAppointment, slug=ra_slug, unit__in=request.units)
    attachment = get_object_or_404(appointment.attachments.all(), slug=attach_slug)
    filename = attachment.contents.name.rsplit('/')[-1]
    resp = StreamingHttpResponse(attachment.contents.chunks(), content_type=attachment.mediatype)
    resp['Content-Disposition'] = 'attachment; filename="' + filename + '"'
    resp['Content-Length'] = attachment.contents.size
    return resp


@requires_role("FUND")
def delete_attachment(request, ra_slug, attach_slug):
    appointment = get_object_or_404(RAAppointment, slug=ra_slug, unit__in=request.units)
    attachment = get_object_or_404(appointment.attachments.all(), slug=attach_slug)
    attachment.hide()
    messages.add_message(request,
                         messages.SUCCESS,
                         'Attachment deleted.'
                         )
    l = LogEntry(userid=request.user.username, description="Hid attachment %s" % attachment, related_object=attachment)
    l.save()
    return HttpResponseRedirect(reverse('ra:view', kwargs={'ra_slug': appointment.slug}))


@requires_role("FUND")
def programs_index(request):
    unit_ids = [unit.id for unit in request.units]
    units = Unit.objects.filter(id__in=unit_ids)
    programs = Program.objects.visible_by_unit(units)
    return render(request, 'ra/programs_index.html', {'programs': programs})


@requires_role("FUND")
def new_program(request):
    if request.method == 'POST':
        form = ProgramForm(request.POST)
        if form.is_valid():
            program = form.save()
            messages.add_message(request,
                                 messages.SUCCESS,
                                 'Program was created')
            l = LogEntry(userid=request.user.username,
                         description="Added program %s" % program,
                         related_object=program)
            l.save()
            return HttpResponseRedirect(reverse('ra:programs_index'))
    else:
        form = ProgramForm()
        form.fields['unit'].choices = [(u.id, u.name) for u in request.units]
    return render(request, 'ra/new_program.html', {'form': form})


@requires_role("FUND")
def delete_program(request, program_id):
    program = get_object_or_404(Program, pk=program_id, unit__in=request.units)
    program.delete()
    messages.add_message(request,
                         messages.SUCCESS,
                         'Program deleted.'
                         )
    l = LogEntry(userid=request.user.username, description="Hid program %s" % program, related_object=program)
    l.save()
    return HttpResponseRedirect(reverse('ra:programs_index'))


@requires_role("FUND")
def edit_program(request, program_slug):
    program = get_object_or_404(Program, slug=program_slug, unit__in=request.units)
    if request.method == 'POST':
        form = ProgramForm(request.POST, instance=program)
        if form.is_valid():
            program = form.save()
            messages.add_message(request,
                                 messages.SUCCESS,
                                 'Program was created')
            l = LogEntry(userid=request.user.username,
                         description="Added program %s" % program,
                         related_object=program)
            l.save()
            return HttpResponseRedirect(reverse('ra:programs_index'))
    else:
        form = ProgramForm(instance=program)
        form.fields['unit'].choices = [(u.id, u.name) for u in request.units]
    return render(request, 'ra/edit_program.html', {'form': form, 'program': program})

