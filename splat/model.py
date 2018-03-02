from __future__ import print_function, division

"""
.. note::
         These are the spectral modeling functions for SPLAT 
"""
# imports: internal
import bz2
import copy
import glob
import gzip
import os
import requests
import shutil
import sys
import time

# imports: external
#import corner
from matplotlib import cm
import matplotlib.pyplot as plt
import numpy
import pandas
from scipy import stats, signal
from scipy.integrate import trapz        # for numerical integration
from scipy.interpolate import griddata, interp1d
import scipy.optimize as op
from astropy.io import ascii            # for reading in spreadsheet
from astropy.table import Table
from astropy.table import unique as tunique
import astropy.units as u
import astropy.constants as const

#from splat._initialize import *
import splat.triangle as triangle             # will want to move this to corner
from splat.initialize import *
from splat.utilities import *
from splat.citations import shortRef
import splat.plot as splot
import splat.photometry as spphot
import splat.empirical as spemp
import splat.evolve as spev
from .core import Spectrum, classifyByIndex, compareSpectra, generateMask

# structure to store models that have been read in
MODELS_READIN = {}

#######################################################
#######################################################
##################   MODEL LOADING  ###################
#######################################################
#######################################################

def info(model=None):
    if model == None:
        model = list(SPECTRAL_MODELS.keys())
    elif isinstance(model,str):
        model = [model]
    for m in model:
        mdl = checkSpectralModelName(m)
        if mdl == False: print('\nNew model named {} is currently loaded'.format(m))
        print('\nModel {}:'.format(mdl))
        if SPECTRAL_MODELS[mdl]['bibcode'] != '':
            print('\tReference: {}'.format(shortRef(SPECTRAL_MODELS[mdl]['bibcode'])))
            print('\tBibcode: {}'.format(SPECTRAL_MODELS[mdl]['bibcode']))
        instr = numpy.array(list(SPECTRAL_MODELS[mdl]['instruments'].keys()))
        numpy.sort(instr)
        f = instr[0]
        for i in instr[1:]: f=f+', {}'.format(i)
        print('\tComputed for instruments {}'.format(f))
        print('\tParameters:')
        p = _loadModelParameters(mdl)
        for m in SPECTRAL_MODEL_PARAMETERS_INORDER:
            if m in list(p.keys()):
                if SPECTRAL_MODEL_PARAMETERS[m]['type'] == 'continuous':
                    print('\t\t{}: {} {} to {} {}'.format(m,numpy.nanmin(p[m]),SPECTRAL_MODEL_PARAMETERS[m]['unit'],numpy.nanmax(p[m]),SPECTRAL_MODEL_PARAMETERS[m]['unit']))
                else:
                    pval = numpy.array(list(set(p[m])))
                    numpy.sort(pval)
                    f = pval[0]
                    for i in pval[1:]: f=f+', {}'.format(i)
                    print('\t\t{}: {} {}'.format(m,f,SPECTRAL_MODEL_PARAMETERS[m]['unit']))
    return 


def addUserModels(folders=[],default_info={},verbose=True):
    '''
    :Purpose:

        Reads in list of folders with properly processed model sets, checks them, and adds them to the SPECTRAL_MODELS global variable

    :Required Inputs:

        None

    :Optional Inputs:

        * :param folders = []: By default model folders are set in the .splat_spectral_models file; 
        alternately (or in addition) folders of models can be included as an input list.
        * :param default_info = {}: default parameter set to use for models; superceded by 'info.txt' file if present in model folder 
        * :param verbose = False: provide verbose feedback

    :Outputs:
        
        None, simply adds new model sets to SPECTRAL_MODELS global variable

    '''
# default information dictionary
    if len(default_info.keys()) == 0:
        default_info = {
            'folder': '', 
            'name': '', 
            'citation': '', 
            'bibcode': '', 
            'altname': [], 
            'default': {'teff': 1500, 'logg': 5.0, 'z': 0.}}

# read in folders specified in .splat_spectral_models
    if os.path.exists(HOME_FOLDER+'/'+EXTERNAL_SPECTRAL_MODELS_FILE):
        with open(HOME_FOLDER+'/'+EXTERNAL_SPECTRAL_MODELS_FILE, 'r') as frd: x = frd.read()
        folders.extend(x.split('\n'))
        if '' in folders: folders.remove('')

# check and read in the new folders in the SPECTRAL_MODELS dictionary
    if len(folders) > 0:
        for i,f in enumerate(folders):
            flag = 0
            minfo = copy.deepcopy(default_info)
            if minfo['folder'] == '': minfo['folder'] = f
            if minfo['name'] == '': minfo['name'] = os.path.normpath(f).split('/')[-1]
            subfiles = os.listdir(minfo['folder'])
# no duplicate models (for now)
            if minfo['name'] in list(SPECTRAL_MODELS.keys()):
                print('\nWarning: spectral model set {} already exists in SPECTRAL_MODELS library; ignoring this one'.format(minfo['name']))
                flag = 1
# make sure RAW directory exists (indicates models have been processed)
            if 'RAW' not in subfiles:
                print('\nWarning: did not find a RAW directory in {}; please process this model set using splat.model._processModels()'.format(minfo['folder']))
                flag = 1
# check for additional information file
            if 'info.txt' not in subfiles:
                print('\nWarning: did not find info.txt file in {}; using default values for model information'.format(minfo['folder']))
            else:
#                try:
                f = minfo['folder']
                with open(f+'/info.txt', 'r') as frd: x = frd.read()
                lines = x.split('\n')
                if '' in lines: lines.remove('')
                lines = [x.split('\t') for x in lines]
                minfo = dict(lines)
                minfo['folder'] = f
                for k in list(default_info.keys()):
                    if k not in list(minfo.keys()): minfo[k] = default_info[k]
                for k in list(SPECTRAL_MODEL_PARAMETERS.keys()):
                    if k in list(minfo.keys()): minfo['default'][k] = minfo[k]
                    if 'default_'+k in list(minfo.keys()): minfo['default'][k] = minfo['default_'+k]
                minfo['altnames'] = minfo['altnames'].split(',')
#                except:
#                    print('\nWarning: problem reading info.txt file in {}; using default values for model information'.format(minfo['folder']))
            if flag == 0:
                if verbose == True: print('Adding {} models to SPLAT model set'.format(minfo['name']))
                SPECTRAL_MODELS[minfo['name']] = copy.deepcopy(minfo)
                del minfo
    return

def _initializeModels(verbose=False):
    '''
    :Purpose:

        Initializes the spectral model set by adding folders to splat.SPECTRAL_MODELS global variable

    :Required Inputs:

        None

    :Optional Inputs:

        * :param verbose = False: provide verbose feedback

    :Outputs:
        
        None

    '''
# default information for a new model    
#    if len(default_info.keys()) == 0:
    default_info = {
        'instruments': {},
        'name': '', 
        'citation': '', 
        'bibcode': '', 
        'altname': [], 
        'default': {'teff': 1500, 'logg': 5.0, 'z': 0.}}

# folders from which models are to be found
    mfolders = [SPLAT_PATH+SPECTRAL_MODEL_FOLDER]

# specified in .splat_spectral_models
    if os.path.exists(EXTERNAL_SPECTRAL_MODELS_FILE):
        with open(EXTERNAL_SPECTRAL_MODELS_FILE, 'r') as frd: x = frd.read()
        mfolders.extend(x.split('\n'))
    if os.path.exists(HOME_FOLDER+'/'+EXTERNAL_SPECTRAL_MODELS_FILE):
        with open(HOME_FOLDER+'/'+EXTERNAL_SPECTRAL_MODELS_FILE, 'r') as frd: x = frd.read()
        mfolders.extend(x.split('\n'))
# specified in environmental variable SPLAT_SPECTRAL_MODELS
    if os.environ.get('SPLAT_SPECTRAL_MODELS') != None:
        mfolders.extend(str(os.environ['SPLAT_SPECTRAL_MODELS']).split(':'))
# check the model folders
    if '' in mfolders: mfolders.remove('')
    rm = []
    for m in mfolders:
        if os.path.exists(m) == False: rm.append(m)
    if len(rm) > 0:
        for m in rm: mfolders.remove(m)
    if len(mfolders) == 0:
        print('\nNo folders containing spectral models were found to be present')
        return
    mfolders = list(set(mfolders))
    if verbose == True:
        print('Spectral model folders:')
        for m in mfolders: print('\t{}'.format(m))

# go through each model folder and check model names
    for i,f in enumerate(mfolders):
        mnames = os.listdir(f)
        rm = []
        for m in mnames:
            if os.path.isdir(os.path.join(f,m))==False: rm.append(m)
        if len(rm) > 0:
            for m in rm: mnames.remove(m)
        if len(mnames) > 0:
            for nm in mnames: 
                fnm = os.path.join(f,nm)
                instruments = os.listdir(fnm)
                name = checkSpectralModelName(nm)
# new model name, add to global variable
# using info.txt data if available                    
                if name == False:
                    name = nm
                    adddict = {'name': name}
                    definfo = copy.deepcopy(default_info)
                    if 'info.txt' in instruments:
                        with open(os.path.join(fnm,'info.txt'), 'r') as frd: x = frd.read()
                        lines = x.split('\n')
                        if '' in lines: lines.remove('')
                        lines = [x.split('\t') for x in lines]
                        adddict = dict(lines)
                        if 'altnames' in list(adddict.keys()): adddict['altnames'] = adddict['altnames'].split(',')
#                    for k in list(SPECTRAL_MODELS[list(SPECTRAL_MODELS.keys())[0]].keys()):
#                        if k not in list(adddict.keys()):
#                            if k in list(default_info.keys()): adddict[k] = definfo[k]
#                            else: adddict[k] = ''
#                    for k in list(default_info.keys()):
#                        if k not in list(minfo.keys()): minfo[k] = default_info[k]

#  this sets the default values - it would be better to just grab one file and set the defaults that way                    
                    if 'default' not in list(adddict.keys()): adddict['default'] = {}
                    for k in list(SPECTRAL_MODEL_PARAMETERS.keys()):
                        if k in list(adddict.keys()): adddict['default'][k] = adddict[k]
                        if 'default_'+k in list(adddict.keys()): adddict['default'][k] = adddict['default_'+k]
#                        if k in list(adddict['default'].keys()): print(k,adddict['default'][k])
#                    print('\nWarning: did not find info.txt file in {}; using default values for model information'.format(minfo['folder']))
#                    adddict['name'] = nm
                    if 'name' not in list(adddict.keys()): adddict['name'] = name
                    if 'instruments' not in list(adddict.keys()): adddict['instruments'] = {}
                    if 'bibcode' not in list(adddict.keys()): adddict['bibcode'] = ''
                    SPECTRAL_MODELS[name] = adddict
                    if verbose==True: print('\nAdded a new model {} with parameters {}'.format(name,adddict))
                    del adddict, definfo
# go through instruments                
                rm = []
                for m in instruments:
                    if os.path.isdir(os.path.join(fnm,m))==False: rm.append(m)
                if len(rm) > 0:
                    for m in rm: instruments.remove(m)
                if len(instruments) > 0:
                    for inst in instruments:
# make sure there are files in this folder
                        fnmi = os.path.join(fnm,inst)
                        mfiles = os.listdir(fnmi)
                        if len(mfiles) > 0:
                            instrument = checkInstrument(inst)
# unknown instrument; just add for now
                            if instrument == False:
                                instrument = (inst.replace(' ','-').replace('_','-')).upper()
                            if instrument not in list(SPECTRAL_MODELS[name]['instruments'].keys()):
                                SPECTRAL_MODELS[name]['instruments'][instrument] = fnmi
                                if verbose == True: print('\nAdding model {} and instrument {} from {}'.format(name,instrument,fnmi))
                            else:
                                if verbose == True: print('\nModel {} and instrument {}: ignoring {} as these already exists in {}'.format(name,instrument,fnmi,SPECTRAL_MODELS[name]['instruments'][instrument]))
    return

_initializeModels()


# helper functions to read in raw models
def _readBurrows06(file):
    if not os.access(file, os.R_OK):
        raise ValueError('Could not find model file {}'.format(file))
    data = ascii.read(os.path.normpath(file),data_start=2)
    if isinstance(data['LAMBDA(mic)'][0],str):
        wave = numpy.array([float(l.replace('D','e')) for l in data['LAMBDA(mic)']])*u.micron
        fnu = numpy.array([float(l.replace('D','e')) for l in data['FNU']])*(u.erg/u.s/u.cm/u.cm/u.Hz)
    else:
        wave = numpy.array(data['LAMBDA(mic)'])*u.micron
        fnu = numpy.array(data['FNU'])*(u.erg/u.s/u.cm/u.cm/u.Hz)
    wave = wave.to(DEFAULT_WAVE_UNIT)
    flux = fnu.to(DEFAULT_FLUX_UNIT,equivalencies=u.spectral_density(wave))
#    print(wave[50],fnu[50],flux[50])
    fluxsort = [x for (y,x) in sorted(zip(wave.value,flux.value))]
    wavesort = sorted(wave.value)
    return wavesort*DEFAULT_WAVE_UNIT, fluxsort*DEFAULT_FLUX_UNIT


def _readVeyette(file,skip=0):
    if not os.access(file, os.R_OK):
        raise ValueError('Could not find model file {}'.format(file))
    data = []
    if file[-3:] == '.gz':
        with gzip.open(os.path.normpath(file),'rt') as f:
            for line in f:
                data.append(line.replace('\n',''))
    else:
        with open(os.path.normpath(file),'rt') as f:
            for line in f:
                data.append(line.replace('\n',''))
    if skip > 0: data = data[skip:]

    wave = numpy.array([float(d.split()[0]) for d in data])*u.Angstrom
    wave = wave.to(DEFAULT_WAVE_UNIT)
    flux = numpy.array([10.**(float(d.split()[1])) for d in data])*u.erg/u.s/u.Angstrom/u.cm/u.cm
    flux = flux.to(DEFAULT_FLUX_UNIT)
    return wave, flux

def _readBtsettl08(file,expon=-8.):
    if not os.access(file, os.R_OK):
        raise ValueError('Could not find model file {}'.format(file))
    data = []
    if file[-3:] == '.gz':
        with gzip.open(os.path.normpath(file),'rt') as f:
            for line in f:
                data.append(line.replace('- ','-').replace('-',' -').replace('D -','D-'))
    elif file[-4:] == '.bz2':
        with bz2.open(os.path.normpath(file),'rt') as f:
            for line in f:
                data.append(line.replace('- ','-').replace('-',' -').replace('D -','D-'))
    else:
        with open(os.path.normpath(file),'rt') as f:
            for line in f:
                data.append(line)
    wave = numpy.array([float((d.split()[0]).replace('D','e'))/1.e4 for d in data])*u.micron
    wave = wave.to(DEFAULT_WAVE_UNIT)
    flux = numpy.array([10.**(float(d.split()[1].replace('D','e'))+expon) for d in data])*u.erg/(u.s*u.Angstrom*u.cm**2)
    flux = flux.to(DEFAULT_FLUX_UNIT,equivalencies=u.spectral_density(wave))
    fluxsort = [x for (y,x) in sorted(zip(wave.value,flux.value))]
    wavesort = sorted(wave.value)
    return wavesort*DEFAULT_WAVE_UNIT, fluxsort*DEFAULT_FLUX_UNIT

def _readAtmos(file):
    try:
        from netCDF4 import Dataset
    except:
        raise ValueError('\nYou must have the netCDF4 package installed, which is part of the Anaconda installation')
    if not os.access(file, os.R_OK):
        raise ValueError('Could not find model file {}'.format(file))
    d = Dataset(file)
    nu = d.variables['nu'][:]/u.cm
    fnu = d.variables['fnu'][:]*u.erg/u.s/u.cm
    wave = (1./nu).to(DEFAULT_WAVE_UNIT)
    flux = (fnu*nu**2).to(DEFAULT_FLUX_UNIT,equivalencies=u.spectral_density(wave))
    fluxsort = [x for (y,x) in sorted(zip(wave.value,flux.value))]
    wavesort = sorted(wave.value)
    return wavesort*DEFAULT_WAVE_UNIT, fluxsort*DEFAULT_FLUX_UNIT

def _readMorley14(file):
    if not os.access(file, os.R_OK):
        raise ValueError('Could not find model file {}'.format(file))
    data = ascii.read(os.path.normpath(file),data_start=4)
    freq = numpy.array(data['col1'])*u.Hz
    wave = freq.to(DEFAULT_WAVE_UNIT,equivalencies=u.spectral())
    flux = numpy.array(data['col2'])*u.erg/(u.s*u.Hz*u.cm**2)
    flux = flux.to(DEFAULT_FLUX_UNIT,equivalencies=u.spectral_density(wave))
    fluxsort = [x for (y,x) in sorted(zip(wave.value,flux.value))]
    wavesort = sorted(wave.value)
    return wavesort*DEFAULT_WAVE_UNIT, fluxsort*DEFAULT_FLUX_UNIT

# this also reads in Morley et al. 2012 models
def _readSaumon12(file):
    if not os.access(file, os.R_OK):
        raise ValueError('Could not find model file {}'.format(file))
    data = ascii.read(os.path.normpath(file),data_start=2)
    wave = numpy.array(data['col1'])*u.micron
    wave = wave.to(DEFAULT_WAVE_UNIT)
    flux = numpy.array(data['col2'])*u.erg/(u.s*u.Hz*u.cm**2)
    flux = flux.to(DEFAULT_FLUX_UNIT,equivalencies=u.spectral_density(wave))
    fluxsort = [x for (y,x) in sorted(zip(wave.value,flux.value))]
    wavesort = sorted(wave.value)
    return wavesort*DEFAULT_WAVE_UNIT, fluxsort*DEFAULT_FLUX_UNIT

# Tremblin
def _readTremblin16(file):
    if not os.access(file, os.R_OK):
        raise ValueError('Could not find model file {}'.format(file))
    data = ascii.read(os.path.normpath(file),data_start=2)
    nu = numpy.array(data['col1'])/u.cm
    fnu = numpy.array(data['col2'])*u.erg/(u.s*u.cm)
    wave = (1./nu).to(u.DEFAULT_WAVE_UNIT)
    flux = (fnu*nu**2).to(splat.DEFAULT_FLUX_UNIT,equivalencies=u.spectral_density(wave))
    flux = flux*((((10.*u.pc)/(0.1*u.Rsun)).to(u.m/u.m))**2)  # scale to surface flux
    fluxsort = [x for (y,x) in sorted(zip(wave.value,flux.value))]
    wavesort = sorted(wave.value)
    return wavesort*DEFAULT_WAVE_UNIT, fluxsort*DEFAULT_FLUX_UNIT

# this also reads in old Drift models
def _readDrift(file):
    if not os.access(file, os.R_OK):
        raise ValueError('Could not find model file {}'.format(file))
    data = ascii.read(os.path.normpath(file))
    wave = numpy.array(data['col1'])*u.micron
    wave = wave.to(DEFAULT_WAVE_UNIT)
    flux = numpy.array(data['col2'])*u.erg/(u.s*u.cm**3)
    flux = flux.to(DEFAULT_FLUX_UNIT,equivalencies=u.spectral_density(wave))
    fluxsort = [x for (y,x) in sorted(zip(wave.value,flux.value))]
    wavesort = sorted(wave.value)
    return wavesort*DEFAULT_WAVE_UNIT, fluxsort*DEFAULT_FLUX_UNIT


# NOTE: THIS FUNCTION IS NO LONGER IN USE
def _modelName(modelset,instrument,param):
# check modelset name
    mset = checkSpectralModelName(modelset)
    if mset == False: raise ValueError('\nInvalid model name {} passed to splat.model._modelName()'.format(modelset))

# set defaults for parameters not included in param

    filename = mset
    for k in SPECTRAL_MODEL_PARAMETERS_INORDER:
        if k in list(SPECTRAL_MODELS[mset]['default'].keys()):
            if k in list(param.keys()): val = param[k] 
            else: val = SPECTRAL_MODELS[mset]['default'][k]
            kstr = '_{}{}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],val)
            if k == 'teff': kstr = '_{}{}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],int(val))
            elif k == 'logg': kstr = '_{}{:.1f}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],float(val))
            elif k == 'z': kstr = '_{}{:.1f}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],float(val)-0.0001)
            filename=filename+kstr
    if modeltype != '': filename=filename+'_{}.txt'.format(modeltype)
    return filename


def _processOriginalModels(sedres=100,instruments=['SED','SPEX-PRISM'],verbose=True,skipraw=True,*args,**kwargs):

    default_info = {
        'instruments': {},
        'name': '', 
        'bibcode': '', 
        'altnames': [], 
        'default': {'teff': 1500, 'logg': 5.0, 'z': 0.}}

# name of model
    mset = False
    if len(args) >= 1: mset = args[0]
    mset = kwargs.get('set',mset)
    mset = kwargs.get('modelset',mset)
    mset = kwargs.get('model',mset)

# input folder
    folder = './'
    if len(args) >=2: folder = args[1]
    folder = kwargs.get('folder',folder)
    folder = kwargs.get('infolder',folder)
    folder = kwargs.get('input_folder',folder)

# output folder
    outputfolder = ''
    if len(args) >=3: outputfolder = args[2]
    outputfolder = kwargs.get('outfolder',outputfolder)
    outputfolder = kwargs.get('output_folder',outputfolder)
    if outputfolder == '': outputfolder = folder

# check folders
    if not os.path.exists(folder):
        raise ValueError('\nCould not find input folder {}'.format(folder))
    if not os.path.exists(outputfolder):
        os.makedirs(outputfolder)

    modelset = checkSpectralModelName(mset)
# generate a new modelset key in SPECTRAL_MODELS
    if modelset == False:
        modelset = mset
        adddict = {'name': modelset,'instruments': {},'bibcode': '','altnames': [],'default': {'teff': 1500, 'logg': 5.0, 'z': 0.}}
        files = os.listdir(folder)
        if 'info.txt' in files:
            with open(os.path.join(folder,'info.txt'), 'r') as frd: x = frd.read()
            lines = x.split('\n')
            if '' in lines: lines.remove('')
            lines = [x.split('\t') for x in lines]
            adddict = dict(lines)
            if 'altnames' in list(adddict.keys()): adddict['altnames'] = adddict['altnames'].split(',')
        for k in list(SPECTRAL_MODELS[list(SPECTRAL_MODELS.keys())[0]].keys()):
            if k not in list(adddict.keys()):
                if k in list(default_info.keys()): adddict[k] = definfo[k]
                else: adddict[k] = ''
        for k in list(SPECTRAL_MODEL_PARAMETERS.keys()):
            if k in list(adddict.keys()): adddict['default'][k] = adddict[k]
            if 'default_'+k in list(adddict.keys()): adddict['default'][k] = adddict['default_'+k]
            files = os.listdir(outputfolder)
            if 'info.txt' not in files:
                shutil.copy(os.path.join(folder,'info.txt'),os.path.join(outputfolder,'info.txt'))
        SPECTRAL_MODELS[modelset] = adddict
        if verbose==True: print('\nAdded a new model {} with parameters {}'.format(modelset,adddict))
        del adddict

# special 'ORIGINAL' folder
    files = os.listdir(folder)
    if 'ORIGINAL' in files: folder = os.path.join(folder,'ORIGINAL')


# only do instruments if RAW models already exist
    skipraw = skipraw and os.path.exists(outputfolder+'/RAW/')
    try:
        skipraw = skipraw and len(os.listdir(outputfolder+'/RAW/')) > 0
    except:
        skipraw = skipraw and False
    if skipraw == False:

# presets for various models - these are based on how they are downloaded
        if 'burrows' in modelset.lower():
            readfxn = _readBurrows06
            files = glob.glob(os.path.join(folder,'*.txt'))
            mparam = {}
            mparam['teff'] = [float(f.split('_')[0].split('T')[-1]) for f in files]
            mparam['logg'] = [float(f.split('_')[1][1:]) for f in files]
            mparam['z'] = [numpy.round(numpy.log10(float(f.split('_')[-1][:3]))*10.)/10. for f in files]
            mparam['cld'] = [f.split('_')[2].replace('cf','nc') for f in files]
        elif 'madhu' in modelset.lower():
            readfxn = _readBurrows06
            files = glob.glob(os.path.join(folder,'*'))
            mparam = {}
            mparam['teff'] = [float(f.split('_')[1].split('t')[-1]) for f in files]
            mparam['logg'] = [float(f.split('_')[2].split('g')[-1]) for f in files]
            mparam['z'] = [numpy.round(numpy.log10(float(f.split('_')[3].split('z')[-1]))*10.)/10. for f in files]
            mparam['fsed'] = [f.split('_')[-1].lower() for f in files]
            mparam['cld'] = [(f.split('/')[-1]).split('_')[0].lower() for f in files]
            mparam['kzz'] = [f.split('_')[-2].lower() for f in files]
        elif 'atmos' in modelset.lower():
            readfxn = _readAtmos
            files = glob.glob(os.path.join(folder,'*.ncdf'))
            mparam = {}
            mparam['teff'] = [float((f.split('/')[-1]).split('_')[1][1:]) for f in files]
            mparam['logg'] = [float((f.split('/')[-1]).split('_')[2][2:]) for f in files]
            mparam['z'] = [0. for f in files]
            mparam['ad'] = [float((f.split('/')[-1]).split('_')[3][1:]) for f in files]
            mparam['logpmin'] = [float((f.split('/')[-1]).split('_')[4][2:]) for f in files]
            mparam['logpmax'] = [float((f.split('/')[-1]).split('_')[5][2:]) for f in files]
            mparam['kzz'] = [(f.split('/')[-1]).split('_')[6][3:] for f in files]
            mparam['broad'] = [(f.split('/')[-1]).split('_')[7] for f in files]
            mparam['cld'] = [(f.split('/')[-1]).split('_')[8] for f in files]
        elif modelset == 'btsettl08':
            readfxn = _readBtsettl08
            files = glob.glob(os.path.join(folder,'*spec.7.gz'))
            mparam = {}
            mparam['teff'] = [float((f.split('/'))[-1][3:6])*100. for f in files]
            mparam['logg'] = [float((f.split('/'))[-1][7:10]) for f in files]
            mparam['z'] = [float((f.split('/'))[-1][10:14]) for f in files]
            mparam['enrich'] = [float(((f.split('/'))[-1].split('a+'))[-1][0:3]) for f in files]
        elif modelset == 'nextgen99':
            readfxn = _readBtsettl08
            files = glob.glob(os.path.join(folder,'lte*.gz'))
            mparam = {}
            mparam['teff'] = [float((f.split('/'))[-1][3:6])*100. for f in files]
            mparam['logg'] = [float((f.split('/'))[-1][7:10]) for f in files]
            mparam['z'] = [float((f.split('/'))[-1][10:14]) for f in files]
        elif modelset == 'btnextgen' or modelset == 'btcond' or modelset == 'btdusty':
            readfxn = _readBtsettl08
            files = glob.glob(os.path.join(folder,'lte*.bz2'))
            mparam = {}
            mparam['teff'] = [float((f.split('/'))[-1][3:6])*100. for f in files]
            mparam['logg'] = [float((f.split('/'))[-1][7:10]) for f in files]
            mparam['z'] = [float((f.split('/'))[-1][10:14]) for f in files]
            if 'enrich' in list(SPECTRAL_MODELS[modelset]['default'].keys()):
                mparam['enrich'] = [float(((f.split('/'))[-1].split('a+'))[-1][0:3]) for f in files]
        elif modelset == 'cond01' or modelset == 'dusty01':
            readfxn = _readBtsettl08
            files = glob.glob(os.path.join(folder,'*7.gz'))
            mparam = {}
            mparam['teff'] = [float((f.split('/'))[-1][3:5])*100. for f in files]
            mparam['logg'] = [float((f.split('/'))[-1][6:9]) for f in files]
            mparam['z'] = [float((f.split('/'))[-1][10:13]) for f in files]
        elif modelset == 'btsettl15':
            readfxn = _readBtsettl08
            files = glob.glob(os.path.join(folder,'*spec.7.gz'))
            mparam = {}
            mparam['teff'] = [float((f.split('/'))[-1][3:8])*100. for f in files]
            mparam['logg'] = [float((f.split('/'))[-1][9:12]) for f in files]
            mparam['z'] = [float((f.split('/'))[-1][12:16]) for f in files]
    # Morley et al. 2012: no metallicity, fsed, kzz or clouds
        elif modelset == 'morley12':
            readfxn = _readSaumon12
            files = glob.glob(os.path.join(folder,'sp*'))
            mparam = {}
            mparam['teff'] = [float((((f.split('/'))[-1].split('_'))[-2].split('g'))[0][1:]) for f in files]
            mparam['logg'] = [2.+numpy.log10(float((((((f.split('/'))[-1].split('_'))[-2].split('g'))[1]).split('f'))[0])) for f in files]
            mparam['z'] = [SPECTRAL_MODELS[modelset]['default']['z'] for f in files]
            mparam['fsed'] = ['f'+((((f.split('/'))[-1].split('_'))[-2].split('g'))[1]).split('f')[-1] for f in files]
    # Morley et al. 2014: no metallicity, fsed, kzz or clouds
        elif modelset == 'morley14':
            readfxn = _readMorley14
            files = glob.glob(os.path.join(folder,'sp*'))
            mparam = {}
            mparam['teff'] = [float((((f.split('/'))[-1].split('_'))[-2].split('g'))[0][1:]) for f in files]
            mparam['logg'] = [2.+numpy.log10(float((((((f.split('/'))[-1].split('_'))[-2].split('g'))[1]).split('f'))[0])) for f in files]
            mparam['z'] = [SPECTRAL_MODELS[modelset]['default']['z'] for f in files]
            mparam['fsed'] = ['f'+(((((f.split('/'))[-1].split('_'))[-2].split('g'))[1]).split('f')[-1]).split('h')[0] for f in files]
            mparam['cld'] = ['h'+(((((f.split('/'))[-1].split('_'))[-2].split('g'))[1]).split('f')[-1]).split('h')[-1] for f in files]
    # Saumon & Marley 2012: no metallicity, fsed, kzz or clouds
        elif modelset == 'saumon12':
            readfxn = _readSaumon12
            files = glob.glob(os.path.join(folder,'sp*'))
            mparam = {}
            mparam['teff'] = [float((((f.split('/'))[-1].split('_'))[-1].split('g'))[0][1:]) for f in files]
            mparam['logg'] = [2.+numpy.log10(float((((f.split('/'))[-1].split('_'))[-1].split('g'))[1].split('nc')[0])) for f in files]
            mparam['z'] = [SPECTRAL_MODELS[modelset]['default']['z'] for f in files]
        elif modelset == 'drift':
            readfxn = _readBtsettl08
            files = glob.glob(os.path.join(folder,'lte_*'))
            mparam['teff'] = [float((f.split('/')[-1]).split('_')[1]) for f in files]
            mparam['logg'] = [float((f.split('/')[-1]).split('_')[2][:3]) for f in files]
            mparam['z'] = [float((f.split('/')[-1]).split('_')[2][3:7]) for f in files]
            mparam = {}
        elif modelset == 'tremblin16':
            readfxn = _readTremblin16
            files = glob.glob(os.path.join(folder,'*.dat'))
            mparam = {}
            mparam['teff'] = [float((f.split('/')[-1]).split('_')[1][1:]) for f in files]
            mparam['logg'] = [float((f.split('/')[-1]).split('_')[2][1:]) for f in files]
            mparam['z'] = [SPECTRAL_MODELS[modelset]['default']['z'] for f in files]
            mparam['kzz'] = [float((f.split('/')[-1]).split('_')[3][1:]) for f in files]
            mparam['ad'] = [float((f.split('/')[-1]).split('_')[5][1:5]) for f in files]
        elif 'veyette' in modelset.lower():
            readfxn = _readVeyette
            files = glob.glob(os.path.join(folder,'*.gz'))
            mparam = {}
            mparam['teff'] = [float((f.replace('.BT-Settl','').replace('.txt.gz','').split('/')[-1]).split('_')[0][3:]) for f in files]
            mparam['logg'] = [float((f.replace('.BT-Settl','').replace('.txt.gz','').split('/')[-1]).split('_')[1]) for f in files]
            mparam['z'] = [float((f.replace('.BT-Settl','').replace('.txt.gz','').split('/')[-1]).split('_')[2][1:].replace('+','')) for f in files]
            mparam['enrich'] = [float((f.replace('.BT-Settl','').replace('.txt.gz','').split('/')[-1]).split('_')[3][1:].replace('+','')) for f in files]
            mparam['carbon'] = [float((f.replace('.BT-Settl','').replace('.txt.gz','').split('/')[-1]).split('_')[4][1:].replace('+','')) for f in files]
            mparam['oxygen'] = [float((f.replace('.BT-Settl','').replace('.txt.gz','').split('/')[-1]).split('_')[5][1:].replace('+','')) for f in files]
        else:
            raise ValueError('\nHave not yet gotten model set {} into _processModels'.format(modelset))

        if len(files) == 0: 
            raise ValueError('Could not find spectral model files in {}'.format(folder))

# create folders if they don't exist
        if not os.path.exists(outputfolder+'/RAW/'):
            os.makedirs(outputfolder+'/RAW/')

# generate photometry - skipping for now since this takes a while
#    if kwargs.get('make_photometry',False) == True: 
#        phot_data = {}
#        for p in SPECTRAL_MODEL_PARAMETERS_INORDER: phot_data[p] = [] 
#        for f in list(FILTERS.keys()): phot_data[f] = []

# read in files
        if verbose == True: print('\nIntegrating {} models into SPLAT'.format(modelset))
        for i,f in enumerate(files):
            try:
                wv,flx = readfxn(f)
    #        spmodel = Spectrum(wave=wv,flux=flx)

            except:
                print('\nError reading in file {}; skipping'.format(f))

            else:
                if verbose == True: 
                    line = ''
                    for k in list(mparam.keys()): line=line+'{}: {}, '.format(k,mparam[k][i])
                    print('Processing {}for model {}'.format(line,modelset))

    # generate raw model
                outputfile = outputfolder+'/RAW/'+modelset
                for k in SPECTRAL_MODEL_PARAMETERS_INORDER:
                    if k in list(mparam.keys()): 
                        if SPECTRAL_MODEL_PARAMETERS[k]['type'] == 'continuous':
                            kstr = '_{}{:.2f}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],float(mparam[k][i]))
                        else:
                            kstr = '_{}{}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],mparam[k][i])
                        if k == 'teff': kstr = '_{}{}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],int(mparam[k][i]))
                        elif k == 'z': kstr = '_{}{:.2f}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],mparam[k][i]-0.0001)
                        outputfile=outputfile+kstr
                outputfile=outputfile+'_RAW.txt'    
    # old way - make table and output it
                t = Table([wv,flx],names=['#wavelength','surface_flux'])
                t.write(outputfile,format='ascii.tab')        
    # now gzip it
                with open(outputfile, 'rb') as f_in, gzip.open(outputfile+'.gz', 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
                os.remove(outputfile)

# if successful, add 'RAW' to instruments list in SPECTRAL_MODELS global variable
        SPECTRAL_MODELS[modelset]['instruments']['RAW'] = outputfolder+'/RAW/'

# generate SED model
#             if make_sed == True:
#                 noutputfile = outputfile.replace('RAW','SED')
# # first smooth relevant piece of spectrum            
# # interpret onto observed wavelength grid
#                 npix = numpy.floor(numpy.log(numpy.nanmax(wv.value)/numpy.nanmin(wv.value))/numpy.log(1.+1./sedres))
#                 wvref = [numpy.nanmin(wv.value)*(1.+1./sedres)**i for i in numpy.arange(npix)]
# # either smooth and remap if SED is higher res than original data, 
# # or integral resample if original data is higher resolution than SED
#                 if len(wv) <= len(wvref):
#                     flxsm = _smooth2resolution(wv.value,flx.value,sedres)
#                     f = interp1d(wv.value,flxsm,bounds_error=False,fill_value=0.)
#                     flxout = f(wvref)
#                 else:
#                     flxout = integralResample(wv.value,flx.value,wvref)
#                 t = Table([wvref,flxout],names=['#wavelength','surface_flux'])
#                 t.write(noutputfile,format='ascii.tab')

# generate instruments
    if len(instruments) > 0:
        wv = getModel(set=modelset,instrument='RAW').wave
        for inst in instruments:
            ins = checkInstrument(inst)
            if ins != False: inst = ins
#            if not os.path.exists(outputfolder+'/{}/'.format(inst)): os.makedirs(outputfolder+'/{}/'.format(inst))
            if verbose == True: print('Processing models for instrument {}'.format(inst))

            if inst=='SPEX-PRISM':
                spref = Spectrum(10001)
                processModelsToInstrument(modelset=modelset,wave=spref.wave,instrument=inst)
            elif inst=='SED':
                INSTRUMENTS['SED']['wave_range'] = [numpy.nanmin(wv),numpy.nanmax(wv)]
                INSTRUMENTS['SED']['resolution'] = sedres
                processModelsToInstrument(modelset=modelset,instrument=inst)
            elif ins != False:
                processModelsToInstrument(modelset=modelset,instrument=inst)
            else:
                print('\nDo not have enough information to generate model set for instrument {}; run this separate with processModelsToInstrument()'.format(inst))

    return


def processModelsToInstrument(instrument_parameters={},wunit=DEFAULT_WAVE_UNIT,funit=DEFAULT_FLUX_UNIT,pixel_resolution=4.,wave=[],wave_range=[],resolution=None,template=None,verbose=False,overwrite=False,*args,**kwargs):
    '''
    :Purpose:

        Converts raw spectral models into instrument-specific model sets, based on pre-defined or 
        supplied information on wavelength range and resolution or a template spectrum

    :Required Inputs:

        * `modelset` or `set`: name of the model set to convert, (for now) must be included in SPLAT distribution; may also be passed as a first argument
        * `instrument` or `instr`: name of the instrument to convert, either a predefined one (splat.INSTRUMENTS.keys()) or place holder for user-specified parameters; may also be passed as a second argument

    :Optional Inputs:

        If a predefined instrument is not used, user must supply one of the following combinations either as keywords or in an `instrument_parameters` dictionary parameter:

        * `wave`: an array containing the wavelengths to sample to; resolution is assumed 2 pixels per resolution element
        * `wave_range` and `resolution`: the first is a two-element array (assumed in microns if not specified), the second the effective resolution, assuming 2 pixels per resolution element
        * `wunit`: the unit for the wavelength axis
        * `funit`: the unit for the flux density axis
        * `template`: a template spectrum object, from which the `wave` array is selected

        * `pixel_resolution` = 4: the number of pixels per resolution element
        * `oversample` = 5: by what factor to oversample the spectral data when smoothing
        * `overscan` = 0.05: percentage of total wavelength range to overextend in order to deal with edge effects in smoothing
        * `method` = 'hanning': filter design for smoothing

    :Outputs:
        
        If necessary, creates a folder in the splat.SPECTRAL_MODEL_FOLDER/[modelset]/[instrument] and outputs the model files

    '''
    method = kwargs.get('method','hamming')
    oversample = kwargs.get('oversample',5.)
    overscan = kwargs.get('overscan',0.05)

# model set
    modelset = False
    if len(args) >= 1: modelset = args[0]
    modelset = kwargs.get('modelset',modelset)
    modelset = kwargs.get('model',modelset)
    modelset = kwargs.get('set',modelset)
    mset = checkSpectralModelName(modelset)
    if mset == False:
        raise ValueError('\nInvalid model set {}'.format(modelset))

# instrument
    instrument = 'SPEX-PRISM'
    if len(args) >= 2: instrument = args[1]
    instrument = kwargs.get('instrument',instrument)
    instrument = kwargs.get('instr',instrument)
    instr = checkInstrument(instrument)

# set up parameters for making model
    if instr != False:
        for r in ['resolution','wave_range','wunit','funit']:
            instrument_parameters[r] = INSTRUMENTS[instr][r]
    else:
        instr = instrument.upper()
        instr = instr.replace(' ','-')

# check if instrument is already set up for this model
    if instr in list(SPECTRAL_MODELS[mset]['instruments'].keys()) and overwrite == False:
        print('\nInstrument {} is already computed for modelset {}; set overwrite = True to overwrite these'.format(instr,mset))
        return

# use a template
    if isinstance(template,splat.core.Spectrum):
        instrument_parameters['wave'] = template.wave
        instrument_parameters['wunit'] = template.wave.unit
        instrument_parameters['funit'] = template.flux.unit
        instrument_parameters['wave_range'] = [numpy.nanmin(template.wave.value),numpy.nanmax(template.wave.value)]

# set wavelength unit
    if 'wunit' not in list(instrument_parameters.keys()): instrument_parameters['wunit'] = wunit
    if not isUnit(instrument_parameters['wunit']): 
        if verbose == True: print('\nWarning: could not interpet unit {} which is type {}; setting wavelength unit to {}'.format(instrument_parameters['wunit'],type(instrument_parameters['wunit'],DEFAULT_WAVE_UNIT)))
        instrument_parameters['wunit'] = DEFAULT_WAVE_UNIT

# set wavelength unit
    if 'funit' not in list(instrument_parameters.keys()): instrument_parameters['funit'] = funit
    if not isUnit(instrument_parameters['funit']): 
        instrument_parameters['funit'] = DEFAULT_FLUX_UNIT

# set wave scale
    if 'wave' not in list(instrument_parameters.keys()): instrument_parameters['wave'] = wave
    if len(instrument_parameters['wave']) > 1:
        if isUnit(instrument_parameters['wave']):
            instrument_parameters['wave'] = instrument_parameters['wave'].to(instrument_parameters['wunit']).value
        if isUnit(instrument_parameters['wave'][0]):
            instrument_parameters['wave'] = [w.to(instrument_parameters['wunit']).value for w in instrument_parameters['wave']]
        instrument_parameters['wave_range'] = [numpy.nanmin(instrument_parameters['wave']),numpy.nanmax(instrument_parameters['wave'])]

# set wavelength range
    if 'wave_range' not in list(instrument_parameters.keys()):
        instrument_parameters['wave_range'] = wave_range
    if len(instrument_parameters['wave_range']) > 1:
        if isUnit(instrument_parameters['wave_range']):
            instrument_parameters['wave_range'] = instrument_parameters['wave_range'].to(instrument_parameters['wunit']).value
        if isUnit(instrument_parameters['wave_range'][0]):
            instrument_parameters['wave_range'] = [w.to(instrument_parameters['wunit']).value for w in instrument_parameters['wave_range']]

# set resolution
    if 'resolution' not in list(instrument_parameters.keys()):
        instrument_parameters['resolution'] = resolution

# generate wavelength vector if just range and resolution given
    if len(instrument_parameters['wave']) <= 1 and instrument_parameters['resolution'] != None and len(instrument_parameters['wave_range']) >= 2:
        effres = instrument_parameters['resolution']*pixel_resolution
        npix = numpy.floor(numpy.log(numpy.nanmax(instrument_parameters['wave_range'])/numpy.nanmin(instrument_parameters['wave_range']))/numpy.log(1.+1./effres))
    #                    print(instr,npix)
        instrument_parameters['wave'] = [numpy.nanmin(instrument_parameters['wave_range'])*(1.+1./effres)**i for i in numpy.arange(npix)]
# final error check
    if len(instrument_parameters['wave']) <= 1:
        raise ValueError('\nCould not set up instrument parameters {}'.format(instrument_parameters))

# generate smoothing wavelength vector
    a = numpy.linspace(0.,len(instrument_parameters['wave'])-1,len(instrument_parameters['wave']))
    b = numpy.linspace(0.,len(instrument_parameters['wave'])-1.,oversample*len(instrument_parameters['wave']))
    f = interp1d(a,instrument_parameters['wave'])
    wave_oversample = f(b)

# grab the raw files
    inputfolder = kwargs.get('inputfolder',os.path.normpath(SPECTRAL_MODELS[mset]['instruments']['RAW']))
    files = glob.glob(os.path.normpath(inputfolder+'/*.txt'))
    if len(files) == 0:
        files = glob.glob(os.path.normpath(inputfolder+'/*.gz'))
        if len(files) == 0:
            raise ValueError('\nCould not find model files in {}'.format(inputfolder))

# set and create folder if it don't exist
    outputfolder = kwargs.get('outputfolder',inputfolder.replace('RAW',instr))
#    if os.path.exists(outputfolder) == True and overwrite==False:
 #       raise ValueError('\nModel output folder {} already exists; set overwrite=True to overwrite'.format(outputfolder))
    if not os.path.exists(outputfolder):
        try:
            os.makedirs(outputfolder)
        except:
            raise OSError('\nCould not create output folder {}'.format(outputfolder))

    if verbose == True: print('Processing model set {} to instrument {}'.format(mset,instr))

    for i,f in enumerate(files):
        if verbose == True: print('{}: Processing model {}'.format(i,f))
        noutputfile = f.replace('RAW',instr).replace('.gz','')
        if not os.path.exists(noutputfile) or (os.path.exists(noutputfile) and overwrite==True):

# read in the model
            spmodel = Spectrum(f,ismodel=True)

# NOTE THAT THE FOLLOWING COULD BE REPLACED BY spmodel.toInstrument()

            spmodel.toWaveUnit(instrument_parameters['wunit'])
            spmodel.toFluxUnit(instrument_parameters['funit'])

# trim relevant piece of spectrum 
            dw = overscan*(numpy.nanmax(instrument_parameters['wave'])-numpy.nanmin(instrument_parameters['wave']))
            wrng = [numpy.nanmax([numpy.nanmin(instrument_parameters['wave']-dw),numpy.nanmin(spmodel.wave.value)])*instrument_parameters['wunit'],\
                    numpy.nanmin([numpy.nanmax(instrument_parameters['wave']+dw),numpy.nanmax(spmodel.wave.value)])*instrument_parameters['wunit']]
            spmodel.trim(wrng)
#            print(instrument_parameters['wave'])

# map onto oversampled grid and smooth; if model is lower resolution, interpolate; otherwise integrate & resample
            if len(spmodel.wave) <= len(wave_oversample):
                fflux = interp1d(spmodel.wave.value,spmodel.flux.value,bounds_error=False,fill_value=0.)
                flux_oversample = fflux(wave_oversample)
            else:
                flux_oversample = integralResample(spmodel.wave.value,spmodel.flux.value,wave_oversample)
            spmodel.wave = wave_oversample*instrument_parameters['wunit']
            spmodel.flux = flux_oversample*spmodel.funit
            spmodel.noise = [numpy.nan for x in spmodel.wave]*spmodel.funit
            spmodel.variance = [numpy.nan for x in spmodel.wave]*(spmodel.funit**2)

# smooth this in pixel space including oversample       
            spmodel._smoothToSlitPixelWidth(pixel_resolution*oversample,method=method)

# resample down to final wavelength scale
            fluxsm = integralResample(spmodel.wave.value,spmodel.flux.value,instrument_parameters['wave'])

# output
            t = Table([instrument_parameters['wave'],fluxsm],names=['#wavelength ({})'.format(spmodel.wave.unit),'surface_flux ({})'.format(spmodel.flux.unit)])
            t.write(noutputfile,format='ascii.tab')
        else:
            if verbose == True: print('\tfile {} already exists; skipping'.format(noutputfile))

# if successful, add this instrument to SPECTRAL_MODELS global variable
    SPECTRAL_MODELS[mset]['instruments'][instr] = outputfolder
    return   



def loadOriginalModel(model='btsettl08',instrument='UNKNOWN',file='',**kwargs):
    '''
    :Purpose: 

        Loads up an original model spectrum at full resolution/spectral range, based on filename or model parameters. 

    :Required Inputs:

        None

    :Optional Inputs:

        :param: **model**: The model set to use; may be one of the following:

            - *btsettl08*: (default) model set from `Allard et al. (2012) <http://adsabs.harvard.edu/abs/2012RSPTA.370.2765A>`_  with effective temperatures of 400 to 2900 K (steps of 100 K); surface gravities of 3.5 to 5.5 in units of cm/s^2 (steps of 0.5 dex); and metallicity of -3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.3, and 0.5 for temperatures greater than 2000 K only; cloud opacity is fixed in this model, and equilibrium chemistry is assumed. Note that this grid is not completely filled and some gaps have been interpolated (alternate designations: `btsettled`, `btsettl`, `allard`, `allard12`)
            - *burrows06*: model set from `Burrows et al. (2006) <http://adsabs.harvard.edu/abs/2006ApJ...640.1063B>`_ with effective temperatures of 700 to 2000 K (steps of 50 K); surface gravities of 4.5 to 5.5 in units of cm/s^2 (steps of 0.1 dex); metallicity of -0.5, 0.0 and 0.5; and either no clouds or grain size 100 microns (fsed = 'nc' or 'f100'). equilibrium chemistry is assumed. Note that this grid is not completely filled and some gaps have been interpolated (alternate designations: `burrows`, `burrows2006`)
            - *morley12*: model set from `Morley et al. (2012) <http://adsabs.harvard.edu/abs/2012ApJ...756..172M>`_ with effective temperatures of 400 to 1300 K (steps of 50 K); surface gravities of 4.0 to 5.5 in units of cm/s^2 (steps of 0.5 dex); and sedimentation efficiency (fsed) of 2, 3, 4 or 5; metallicity is fixed to solar, equilibrium chemistry is assumed, and there are no clouds associated with this model (alternate designations: `morley2012`)
            - *morley14*: model set from `Morley et al. (2014) <http://adsabs.harvard.edu/abs/2014ApJ...787...78M>`_ with effective temperatures of 200 to 450 K (steps of 25 K) and surface gravities of 3.0 to 5.0 in units of cm/s^2 (steps of 0.5 dex); metallicity is fixed to solar, equilibrium chemistry is assumed, sedimentation efficiency is fixed at fsed = 5, and cloud coverage fixed at 50% (alternate designations: `morley2014`)
            - *saumon12*: model set from `Saumon et al. (2012) <http://adsabs.harvard.edu/abs/2012ApJ...750...74S>`_ with effective temperatures of 400 to 1500 K (steps of 50 K); and surface gravities of 3.0 to 5.5 in units of cm/s^2 (steps of 0.5 dex); metallicity is fixed to solar, equilibrium chemistry is assumed, and no clouds are associated with these models (alternate designations: `saumon`, `saumon2012`)
            - *drift*: model set from `Witte et al. (2011) <http://adsabs.harvard.edu/abs/2011A%26A...529A..44W>`_ with effective temperatures of 1700 to 3000 K (steps of 50 K); surface gravities of 5.0 and 5.5 in units of cm/s^2; and metallicities of -3.0 to 0.0 (in steps of 0.5 dex); cloud opacity is fixed in this model, equilibrium chemistry is assumed (alternate designations: `witte`, `witte2011`, `helling`)
            - *madhusudhan*: model set from `Madhusudhan et al. (2011) <http://adsabs.harvard.edu/abs/2011ApJ...737...34M>`_ with effective temperatures of 600 K to 1700 K (steps of 50-100 K); surface gravities of 3.5 and 5.0 in units of cm/s^2; and metallicities of 0.0 to 1.0 (in steps of 0.5 dex); there are multiple cloud prescriptions for this model, equilibrium chemistry is assumed (alternate designations: `madhusudhan`)
        
        :param: **teff**: effective temperature of the model in K (e.g. `teff` = 1000)
        :param: **logg**: log10 of the surface gravity of the model in cm/s^2 units (e.g. `logg` = 5.0)
        :param: **z**: log10 of metallicity of the model relative to solar metallicity (e.g. `z` = -0.5)
        :param: **fsed**: sedimentation efficiency of the model (e.g. `fsed` = 'f2')
        :param: **cld**: cloud shape function of the model (e.g. `cld` = 'f50')
        :param: **kzz**: vertical eddy diffusion coefficient of the model (e.g. `kzz` = 2)
        :param: **instrument**: instrument the model should be converted to (default = 'raw')
        :param: **file**: file name for model (default = '' or generated from parameters)
        :param: **folder**: folder containing file (default = '' or default folder for model set)
        :param: **verbose**: give lots of feedback

    :Output:

        A SPLAT Spectrum object of the model with wavelength in microns and surface fluxes in F_lambda units of erg/cm^2/s/micron.

    :Example:

    >>> import splat
    >>> mdl = splat.loadOriginalModel(model='btsettl',teff=2600,logg=4.5)
    >>> mdl.info()
        btsettl08 Teff=2600 logg=4.5 [M/H]=0.0 atmosphere model with the following parmeters:
        Teff = 2600 K
        logg = 4.5 dex
        z = 0.0 dex
        fsed = nc
        cld = nc
        kzz = eq

        If you use this model, please cite Allard, F. et al. (2012, Philosophical Transactions of the Royal Society A, 370, 2765-2777)
        bibcode = 2012RSPTA.370.2765A
    '''

    mkwargs = {}
    mkwargs['ismodel'] = True
    
# check modelset name
    mset = checkSpectralModelName(model)
    if mset == False:
        raise ValueError('\{} is not a valid model set name'.format(model))
    mkwargs['model'] = mset

# if not a specific file, generate it
    if file == '':
        for k in list(SPECTRAL_MODEL_PARAMETERS.keys()):
            mkwargs[k] = kwargs.get(k,SPECTRAL_MODEL_PARAMETERS[k]['default'])
        if mset == 'btsettl08':
            readfxn = _readBtsettl08
            file = os.path.normpath(SPECTRAL_MODELS[mset]['rawfolder']+'lte{:s}-{:.1f}{:.1f}a+0.0.BT-Settl.spec.7.gz'.format(str((float(mkwargs['teff'])+0.01)/1.e5)[2:5],mkwargs['logg'],mkwargs['z']-0.0001))
        elif mset == 'madhusudhan11':
            readfxn = _readBurrows06
            file = os.path.normpath(SPECTRAL_MODELS[mset]['rawfolder']+'{:s}_t{:.0f}_g{:.2f}_z{:.0f}_{:s}_{:s}'.format(mkwargs['cld'].upper(),int(mkwargs['teff']),float(mkwargs['logg']),10.**float(mkwargs['z']),mkwargs['kzz'].lower(),mkwargs['fsed'].lower()))
        elif mset == 'saumon12':
            readfxn = _readSaumon12
            file = os.path.normpath(SPECTRAL_MODELS[mset]['rawfolder']+'sp_t{:.0f}g{:.0f}{:s}'.format(int(mkwargs['teff']),10.**(float(mkwargs['logg'])-2.),mkwargs['cld'].lower()))
        else:
            raise ValueError('\nDo not yet have {} models in loadOriginalModel'.format(mset))


# check file name
    if not os.access(file, os.R_OK):
#        filetmp = SPECTRAL_MODELS[mset]['rawfolder']+file
#        if not os.access(filetmp, os.R_OK):
        raise ValueError('Could not find model file {}'.format(file))
#        else: file=filetmp
    mkwargs['filename'] = os.path.basename(file)

# read in data            
    wave,flux = readfxn(file)
    mkwargs['wave'] = wave
    mkwargs['flux'] = flux

# convert to instrument - TBD
    mkwargs['instrument'] = instrument

    return Spectrum(**mkwargs)


def loadOriginalInterpolatedModel(model='btsettl08',teff=2000,logg=5.0,**kwargs):
    '''
    :Purpose: 

        Loads up an original model spectrum at full resolution/spectral range, interpolated by temperature and surface gravity

    :Required Inputs:

        None

    :Optional Inputs:

        same as .. `loadOriginalModel()`_

    .. _`loadOriginalModel()` : api.html#splat.model.loadOriginalModel

    :Output:

        A SPLAT Spectrum object of the model with wavelength in microns and surface fluxes in F_lambda units of erg/cm^2/s/micron.

    :Example:

    >>> import splat
    >>> mdl = splat.loadOriginalInterpolatedModel(model='btsettl',teff=2632,logg=4.6)
    >>> mdl.info()
        BT-Settl (2008) Teff=2632 logg=4.6 atmosphere model with the following parmeters:
        Teff = 2632 K
        logg = 4.6 dex
        z = 0.0 dex
        fsed = nc
        cld = nc
        kzz = eq

        If you use this model, please cite Allard, F. et al. (2012, Philosophical Transactions of the Royal Society A, 370, 2765-2777)
        bibcode = 2012RSPTA.370.2765A
    '''
    teffs = [100*numpy.floor(teff/100.),100*numpy.ceil(teff/100.)]
    loggs = [0.5*numpy.floor(logg*2.),0.5*numpy.ceil(logg*2.)]

    wt = numpy.log10(teffs[1]/teff)/numpy.log10(teffs[1]/teffs[0])
    wg = (loggs[1]-logg)/(loggs[1]-loggs[0])
    weights = numpy.array([wt*wg,(1.-wt)*wg,wt*(1.-wg),(1.-wt)*(1.-wg)])
    weights/=numpy.sum(weights)

    models = []
    models.append(loadOriginalModel(model=model,teff=teffs[0],logg=loggs[0],**kwargs))
    if teffs[1]==teffs[0]:
        models.append(models[-1])
    else:
        models.append(loadOriginalModel(model=model,teff=teffs[1],logg=loggs[0],**kwargs))
    if loggs[1]==loggs[0]:
        models.extend(models[0:1])
    else:
        models.append(loadOriginalModel(model=model,teff=teffs[0],logg=loggs[1],**kwargs))
        models.append(loadOriginalModel(model=model,teff=teffs[1],logg=loggs[1],**kwargs))
                                                            
    flx = []
    for i in range(len(models[0].flux)):
        val = numpy.array([numpy.log10(m.flux.value[i]) for m in models])
        flx.append(10.**(numpy.sum(val*weights)))

    mdl_return = models[0]
    mdl_return.flux = flx*models[0].flux.unit
    mdl_return.teff = teff
    mdl_return.logg = logg
    mdl_return.name = '{} Teff={} logg={}'.format(splat.SPECTRAL_MODELS[checkSpectralModelName(model)]['name'],teff,logg)
    
    return mdl_return

# make model function
def makeForwardModel(parameters,data,atm=None,binary=False,duplicate=False,model=None,model1=None,model2=None,instkern=None,contfitdeg=5,return_nontelluric=False,checkplots=False,checkprefix='tmp',verbose=True):
    '''
    parameters may contain any of the following:
        - **modelparam** or **modelparam1**: dictionary of model parameters for primary if model not provided in model or model1: {modelset,teff,logg,z,fsed,kzz,cld,instrument}
        - **modelparam2**: dictionary of model parameters for secondary if model not provided in model2: {modelset,teff,logg,z,fsed,kzz,cld,instrument}
        - **rv** or **rv1**: radial velocity of primary
        - **rv2**: radial velocity of secondary
        - **vsini** or **vsini1**: rotational velocity of primary
        - **vsini2**: rotational velocity of secondary
        - **f21**: relative brightness of secondary to primary (f21 <= 1)
        - **alpha**: exponent to scale telluric absorption 
        - **vinst**: instrument velocity broadening profile if instrkern not provided
        - **vshift**: instrument velocity shift
        - **continuum**: polynomial coefficients for continuum correction; if not provided, a smooth continuum will be fit out
    '''
# check inputs

    if 'modelset' in list(parameters.keys()) and 'modelset1' not in list(parameters.keys()): parameters['modelset1'] = parameters['modelset']
    if 'set' in list(parameters.keys()) and 'modelset1' not in list(parameters.keys()): parameters['modelset1'] = parameters['set']
    if 'set1' in list(parameters.keys()) and 'modelset1' not in list(parameters.keys()): parameters['modelset1'] = parameters['set1']
    if 'set2' in list(parameters.keys()) and 'modelset2' not in list(parameters.keys()): parameters['modelset2'] = parameters['set2']

# data
    if data != None:
        if isinstance(data,splat.Spectrum) == False:
            raise ValueError('\nData {} must be a Spectrum object'.format(data))

# model / model parameters
    if model1 == None and model1 != None: model1 = copy.deepcopy(model)

    if model1 != None:
        if isinstance(model1,splat.Spectrum) == False:
            raise ValueError('\nModel for primary source {} must be a Spectrum object'.format(model1))
    else:
        if 'modelset1' not in list(parameters.keys()): raise ValueError('\nMust provide model parameters for primary')

    if binary == True and model2 == None and 'modelset2' not in list(parameters.keys()): 
        parameters['modelset2'] = parameters['modelset1']

    if binary == True:
        if model2 != None:
            if isinstance(model2,splat.Spectrum) == False:
                raise ValueError('\nModel for secondary source {} must be a Spectrum object'.format(model2))
        elif 'modelset2' not in list(parameters.keys()): 
            raise ValueError('\nMust provide model parameters for secondary')

    if 'modelset1' in list(parameters.keys()):
        mset1 = checkSpectralModelName(parameters['modelset1'])
        if mset1 != False: parameters['modelset1'] = mset1
        else: raise ValueError('Unknown model set {} for primary'.format(parameters['modelset1']))

    if 'modelset2' in list(parameters.keys()):
        mset2 = checkSpectralModelName(parameters['modelset2'])
        if mset2 != False: parameters['modelset2'] = mset2
        else: raise ValueError('Unknown model set {} for primary'.format(parameters['modelset2']))

    if 'instrument' not in list(parameters.keys()): parameters['instrument'] = 'RAW'
    if parameters['instrument'] not in list(splat.SPECTRAL_MODELS[parameters['modelset1']]['instruments'].keys()):
        raise ValueError('Instrument {} has not been established for model {}'.format(parameters['instrument'],parameters['modelset1']))

# telluric absorption
    if atm != None:
        if isinstance(atm,splat.Spectrum) == False:
            raise ValueError('\nModel for atmosphere {} must be a Spectrum object'.format(atm))

# establish model spectrum
    if model1 != None:
        mdl1 = copy.deepcopy(model1)
    else:
# read in new model
        mparam = {'modelset': parameters['modelset1'], 'instrument': parameters['instrument']}
        for m in list(splat.SPECTRAL_MODELS[parameters['modelset1']]['default'].keys()):
            if m in list(parameters.keys()): mparam[m] = parameters[m]
            if '{}1'.format(m) in list(parameters.keys()): mparam[m] = parameters['{}1'.format(m)]
        try:
            mdl1 = getModel(**mparam)
        except:
            raise ValueError('\nError in creating primary model with parameters {}'.format(mparam))
#        print(mparam)
#        mdl1.info()

# add in secondary if desired
    if binary==True:
        if duplicate == True:
            mdl2 = copy.deepcopy(mdl1)
        elif model2 != None:
            mdl2 = copy.deepcopy(model2)
        else:
            mparam = {'modelset': parameters['modelset2'], 'instrument': parameters['instrument']}
            for m in list(splat.SPECTRAL_MODELS[parameters['modelset2']]['default'].keys()):
                if '{}2'.format(m) in list(parameters.keys()): mparam[m] = parameters['{}2'.format(m)]
            if len(list(mparam.keys())) == 2:
                print('Warning: no parameters provided for secondary; assuming a duplicate model')
                mdl2 = copy.deepcopy(mdl1)
            else:
                try: 
                    mdl2 = getModel(**mparam)
                except:
                    raise ValueError('\nError in creating secondary model with parameters {}'.format(mparam))
#        mdl2.info()

# make sure everything is on the same wavelength range
    if atm != None:
        atm.toWaveUnit(data.wave.unit)
    mdl1.toWaveUnit(data.wave.unit)    
    if binary == True: 
        mdl2.toWaveUnit(data.wave.unit)    

# visualize spectra for error checking
        if checkplots==True:
            splot.plotSpectrum(mdl1,mdl2,colors=['k','r'],legend=['Model 1','Model 2'],file=checkprefix+'_model.pdf')
    else:
        if checkplots==True:
            splot.plotSpectrum(mdl1,colors=['k'],legend=['Model 1'],file=checkprefix+'_model.pdf')


# apply rv shift and vsini broadening the model spectrum
    if 'rv' in list(parameters.keys()):
        mdl1.rvShift(parameters['rv'])
    elif 'rv1' in list(parameters.keys()):
        mdl1.rvShift(parameters['rv1'])
    if 'vsini' in list(parameters.keys()):
        mdl1.broaden(parameters['vsini'],method='rotation')
    elif 'vsini1' in list(parameters.keys()):
        mdl1.broaden(parameters['vsini1'],method='rotation')
    if binary==True:
        if 'f2' in list(parameters.keys()):
            mdl2.scale(parameters['f2'])
        if 'rv2' in list(parameters.keys()):
            mdl2.rvShift(parameters['rv2'])
        if 'vsini2' in list(parameters.keys()):
            mdl2.broaden(parameters['vsini2'],method='rotation')

# add primary and secondary back together
        mdl = mdl1+mdl2
    else:
        mdl = mdl1

# read in telluric, scale & apply
    if atm != None:
# integral resample telluric profile onto mdl flux range
        atmapp = copy.deepcopy(atm)
        if len(atmapp.flux) != len(mdl.flux):
            funit = atmapp.flux.unit
#            atmapp.flux = splat.integralResample(atmapp.wave.value,atmapp.flux.value,mdl.wave.value)
            atmapp.flux = splat.reMap(atmapp.wave.value,atmapp.flux.value,mdl.wave.value)
            atmapp.flux = atmapp.flux*funit
            atmapp.wave = mdl.wave
            atmapp.noise = [numpy.nan for f in atmapp.flux]*funit
            atmapp.variance = [numpy.nan for f in atmapp.flux]*(funit**2)
        if 'alpha' in list(parameters.keys()):
            atmapp.flux = [t**parameters['alpha'] for t in atmapp.flux.value]*atmapp.flux.unit
        mdlt = mdl*atmapp 
        if checkplots==True:
            splot.plotSpectrum(mdlt,mdl,colors=['r','k'],legend=['Model x Atmosphere','Model'],file=checkprefix+'_modelatm.pdf')
    else: mdlt = copy.deepcopy(mdl)

# resample original and telluric corrected models onto data wavelength range
    funit = mdl.flux.unit
    mdlsamp = copy.deepcopy(mdl)
#    mdlsamp.flux = splat.integralResample(mdl.wave.value,mdl.flux.value,data.wave.value)
    mdlsamp.flux = splat.reMap(mdl.wave.value,mdl.flux.value,data.wave.value)
    mdlsamp.flux = mdlsamp.flux*funit
    mdlsamp.wave = data.wave
    mdlsamp.noise = [numpy.nan for f in mdlsamp.flux]*funit
    mdlsamp.variance = [numpy.nan for f in mdlsamp.flux]*(funit**2)
    funit = mdlt.flux.unit
    mdltsamp = copy.deepcopy(mdlt)
#    mdltsamp.flux = splat.integralResample(mdlt.wave.value,mdlt.flux.value,data.wave.value)
    mdltsamp.flux = splat.reMap(mdlt.wave.value,mdlt.flux.value,data.wave.value)
    mdltsamp.flux = mdltsamp.flux*funit
    mdltsamp.wave = data.wave
    mdltsamp.noise = [numpy.nan for f in mdltsamp.flux]*funit
    mdltsamp.variance = [numpy.nan for f in mdltsamp.flux]*(funit**2)
    if checkplots==True:
        splot.plotSpectrum(mdltsamp,mdlsamp,colors=['r','k'],legend=['Model x Atmosphere','Model'],file=checkprefix+'_modelatmsamp.pdf')


# broaden by instrumental profile
    if instkern != None:
        mdlsamp.broaden(parameters['vinst'],kern=instkern)
        mdltsamp.broaden(parameters['vinst'],kern=instkern)        
    elif 'vinst' in list(parameters.keys()):
        mdlsamp.broaden(parameters['vinst'],method='gaussian')
        mdltsamp.broaden(parameters['vinst'],method='gaussian')
    if checkplots==True:
        splot.plotSpectrum(mdltsamp,mdlsamp,colors=['r','k'],legend=['Model x Atmosphere','Model'],file=checkprefix+'_modelatmsampbroad.pdf')

# apply flux offset (e.g. poor background subtraction)
    if 'offset' in list(parameters.keys()):
        funit = mdlsamp.flux.unit
        mdlsamp.flux = [m+parameters['offset'] for m in mdlsamp.flux.value]*funit
        funit = mdltsamp.flux.unit
        mdltsamp.flux = [m+parameters['offset'] for m in mdltsamp.flux.value]*funit
    if 'offset_fraction' in list(parameters.keys()):
        funit = mdlsamp.flux.unit
        mdlsamp.flux = [m+parameters['offset_fraction']*numpy.median(mdlsamp.flux.value) for m in mdlsamp.flux.value]*funit
        funit = mdltsamp.flux.unit
        mdltsamp.flux = [m+parameters['offset_fraction']*numpy.median(mdltsamp.flux.value) for m in mdltsamp.flux.value]*funit

# correct for continuum
    mdlcont = copy.deepcopy(mdlsamp)
    mdltcont = copy.deepcopy(mdltsamp)

    if 'continuum' in list(parameters.keys()):
        mdlcont.flux = mdlcont.flux*numpy.polyval(parameters['continuum'],mdlcont.wave.value)
        mdltcont.flux = mdlcont.flux*numpy.polyval(parameters['continuum'],mdltcont.wave.value)
    else:
        mdldiv = data/mdltsamp
        mdldiv.smooth(pixels=20)
# NOTE: this fails if there are any nans around    

        pcont = numpy.polyfit(mdldiv.wave.value,mdldiv.flux.value,contfitdeg)
#        f = interp1d(data.wave.value,data.flux.value)
#        pcont = numpy.polyfit(mdltfinal.wave.value,f(mdltfinal.wave.value)/mdltfinal.flux.value,contfitdeg)
        mdlcont.flux = mdlcont.flux*numpy.polyval(pcont,mdlcont.wave.value)
        mdltcont.flux = mdltcont.flux*numpy.polyval(pcont,mdltcont.wave.value)
    if checkplots==True:
        mdltmp = copy.deepcopy(mdlsamp)
        mdldiv = data/mdltsamp
        mdltmp.scale(numpy.nanmedian(mdldiv.flux.value))
        splot.plotSpectrum(mdltcont,mdlcont,data,colors=['r','k','b'],legend=['Model x Atmosphere x Continuum','Model','Data'],file=checkprefix+'_modelatmsampbroadcont.pdf')


# correct for velocity shift (wavelength calibration error)
    mdlfinal = copy.deepcopy(mdlcont)
    mdltfinal = copy.deepcopy(mdltcont)
    if 'vshift' in list(parameters.keys()):
        mdlfinal.rvShift(parameters['vshift'])
        mdltfinal.rvShift(parameters['vshift'])

# return model
    mdlfinal.name = '{} model'.format(parameters['modelset1'])
    mdltfinal.name = '{} model x Atmosphere'.format(parameters['modelset1'])
    if return_nontelluric == True:
        return mdltfinal,mdlfinal
    else:
        return mdltfinal
        

# MCMC loop
def mcmcForwardModelFit(data,param0,param_var,model=None,limits={},nwalkers=1,nsteps=100,nsniffs=1,dof=0.,binary=False,duplicate=False,secondary_model=None,atm=None,report=True,report_index=10,report_each=False,file='tmp',output='all',verbose=True,**kwargs):
    '''
    :Purpose:

        Conducts and Markov Chain Monte Carlo (MCMC) forward modeling fit of a spectrum. 
        This routine assumes the spectral data have already been wavelength calibrated
        THIS ROUTINE IS CURRENTLY IN DEVELOPMENT

    :Required Inputs:

        :param data: Spectrum object containing the data to be modeled
        :param param0: dictionary containing the initial parameters; allowed parameters are the same as those defined in `makeForwardModel()`_
        :param param_var: dictionary containing the scales (gaussian sigmas) over which the parameters are varied at each iteration; should contain the same elements as param0. If a parameter var is set to 0, then that parameter is held fixed

    :Optional Inputs:

        :param: limits = {}: dictionary containing the limits of the parameters; each parameter that is limited should be matched to a two-element list defining the upper and lower bounds
        :param: nwalkers = 1: number of MCMC walkers
        :param: nsteps = 100: number of MCMC steps taken by each walker; the actual number of fits is nsteps x # parameters
        :param: dof: degrees of freedom; if not provided, assumed to be the number of datapoints minus the number of varied parameters
        :param: binary = False: set to True to do a binary model fit
        :param: secondary_model = None: if binary = True, use this parameter to specify the model of the secondary
        :param: model = None: Spectrum object containing the spectral model to use if assumed fixed; should be of higher resolution and wider wavelength range than the data
        :param: atm = None: Spectrum object containing the atmospheric/instrumental transmission profile (e.g., `loadTelluric()`_); should be of higher resolution and wider wavelength range than the data
        :param: report = True: set to True to iteratively report the progress of the fit 
        :param: report_index = 10: if report = True, the number of steps to provide an interim report 
        :param: report_each = False: set to True to save all reports separately (useful for movie making)
        :param: file = 'tmp': file prefix for outputs; should include full path unless in operating in desired folder
        :param: output = 'all': what to return on completion; options include:

            * 'all': (default) return a list of all parameter dictionaries and chi-square values
            * 'best': return only a single dictionary of the best fit parameters and the best fit chi-square value

        :param: verbose = False: provide extra feedback

        mcmcForwardModelFit() will also take as inputs the plotting parameters for `mcmcForwardModelReport()`_ and `plotSpectrum()`_

    :Outputs:
        
        Depending on what is set for the `output` parameter, a list or single dictionary containing model parameters, and a list or single best chi-square values.
        These outputs can be fed into `mcmcForwardModelReport()`_ to visualize the best fitting model and parameters

    :Example:

    >>> import splat
    >>> import splat.model as spmdl
    >>> import astropy.units as u
    >>> # read in spectrum
    >>> sp = splat.Spectrum('nirspec_spectrum.txt')
    >>> # read in and trim model
    >>> mdl = spmdl.loadModel(model='btsettl',teff=2600,logg=5.0,raw=True)
    >>> mdl.trim([numpy.min(sp.wave)-0.01*u.micron,numpy.max(sp.wave)+0.01*u.micron])
    >>> # read in and trim atmospheric absorption
    >>> atm = spmdl.loadTelluric(wave_range=[numpy.min(mdl.wave.value)-0.02,numpy.max(mdl.wave.value)+0.02],output='spec')
    >>> # inital parameters
    >>> mpar = {'rv': 0., 'vsini': 10., 'vinst': 5., 'alpha': 0.6}
    >>> mvar = {'rv': 1., 'vsini': 1., 'vinst': 0.2, 'alpha': 0.05}
    >>> mlim = {'vsini': [0.,500.], 'alpha': [0.,100.]}
    >>> # do fit
    >>> pars,chis = spmdl.mcmcForwardModelFit(sp,mdl,mpar,mvar,limits=mlim,atm=atm,nsteps=100,file='fit'')
    >>> # visualize results
    >>> spmdl.mcmcForwardModelReport(sp,mdl,pars,chis,file='fit',chiweights=True,plotParameters=['rv','vsini'])

    '''    
# generate first fit
    if dof == 0.: dof = int(len(data.wave)-len(list(param0.keys())))
    mdl = makeForwardModel(param0,data,binary=binary,duplicate=duplicate,atm=atm,model=model,model2=secondary_model)
    chi0,scale = splat.compareSpectra(data,mdl)
    parameters = [param0]
    chis = [chi0]
    for i in range(nsteps):
        for k in list(param_var.keys()):
            if param_var[k] != 0.:
                param = copy.deepcopy(param0)
                param[k] = numpy.random.normal(param[k],param_var[k])
# force within range with soft bounce            
                if k in list(limits.keys()):
                    if param[k] < numpy.min(limits[k]): param[k] = numpy.min(limits[k])+numpy.random.uniform()*(numpy.min(limits[k])-param[k])
                    if param[k] > numpy.max(limits[k]): param[k] = numpy.max(limits[k])-numpy.random.uniform()*(param[k]-numpy.max(limits[k]))
                mdl = makeForwardModel(param,data,binary=binary,duplicate=duplicate,atm=atm,model=model,model2=secondary_model)
                chi,scale = splat.compareSpectra(data,mdl)            
#            if stats.f.cdf(chi/chi0, dof, dof) < numpy.random.uniform(0,1):
                if stats.f.cdf(chi/numpy.nanmin(chis), dof, dof) < numpy.random.uniform(0,1):
                    param0 = copy.deepcopy(param)
                    chi0 = chi
                parameters.append(param0)
                chis.append(chi0)
                if verbose == True:
                    l = 'Step {}: chi={:.0f}, dof={}'.format(i,chis[-1],dof)
                    for k in list(param_var.keys()): 
                        if param_var[k] != 0.: l+=' , {}={:.2f}'.format(k,parameters[-1][k])
                    print(l)

# report where we are            
        if report == True and i % int(report_index) == 0 and i > 0:
#            l = 'Step {}: chi={:.0f}, dof={}'.format(i,chis[-1],dof)
#            for k in list(param0.keys()): 
#                if isinstance(parameters[-1][k],float): l+=' , {}={:.2f}'.format(k,parameters[-1][k])
#                else: l+=' , {}={}'.format(k,parameters[-1][k])
#            print(l)

            ibest = numpy.argmin(chis)
            best_parameters = parameters[ibest]
            l = '\nBest chi={:.0f}, dof={}'.format(chis[ibest],dof)
            for k in list(param0.keys()): 
                if isinstance(best_parameters[k],float): l+=' , {}={:.2f}'.format(k,best_parameters[k])
                else: l+=' , {}={}'.format(k,best_parameters[k])
            print(l)

            # mdl,mdlnt = makeForwardModel(parameters[-1],data,binary=binary,atm=atm,model=model,return_nontelluric=True)
            # chi,scale = splat.compareSpectra(data,mdl)            
            # mdl.scale(scale)
            # mdlnt.scale(scale)
            # splot.plotSpectrum(data,mdlnt,mdl,data-mdl,colors=['k','g','r','b'],legend=['Data','Model','Model+Telluric','Difference\nChi2={:.0f}'.format(chi)],figsize=kwargs.get('figsize',[15,5]),file=file+'_interimComparison.pdf')

            # mdl,mdlnt = makeForwardModel(best_parameters,data,binary=binary,atm=atm,model=model,return_nontelluric=True)
            # chi,scale = splat.compareSpectra(data,mdl)
            # mdl.scale(scale)
            # mdlnt.scale(scale)
            # splot.plotSpectrum(data,mdlnt,mdl,data-mdl,colors=['k','g','r','b'],legend=['Data','Model-Telluric','Best Model\nChi2={:.0f}'.format(chi),'Difference'],figsize=kwargs.get('figsize',[15,5]),file=file+'_bestModel.pdf')

            # f = open(file+'_report.txt','w')
            # f.write('steps completed = {}\n'.format(i))
            # f.write('best chi^2 = {:.0f}\n'.format(chis[i]))
            # f.write('degrees of freedom = {:.0f}\n'.format(dof))
            # for k in list(param0.keys()): f.write('{} = {:.2f}\n'.format(k,best_parameters[k]))
            # f.close()

            final_parameters = {}
            for k in list(param0.keys()):
                vals = []
                for i in range(len(parameters)): vals.append(parameters[i][k])
                final_parameters[k] = vals

            mcmcForwardModelReport(data,final_parameters,chis,dof=dof,atm=atm,file=file,binary=binary,duplicate=duplicate,verbose=verbose,**kwargs)

# identify best model
    ibest = numpy.argmin(chis)
    best_chi = chis[ibest]
    best_parameters = parameters[ibest]

# reformat parameters
    final_parameters = {}
    for k in list(param0.keys()):
        vals = []
        for i in range(len(parameters)): vals.append(parameters[i][k])
        final_parameters[k] = vals

    if report == True:
        l = 'Best chi={:.0f}, dof={}'.format(best_chi,dof)
        for k in list(best_parameters.keys()): 
            if isinstance(best_parameters[k],float): l+=' , {}={:.2f}'.format(k,best_parameters[k])
            else: l+=' , {}={}'.format(k,best_parameters[k])
        print(l)

        mcmcForwardModelReport(data,final_parameters,chis,dof=dof,atm=atm,file=file,binary=binary,duplicate=duplicate,verbose=verbose,**kwargs)

        # mdl,mdlnt = makeForwardModel(best_parameters,data,binary=binary,atm=atm,model=model,return_nontelluric=True)
        # chi0,scale = splat.compareSpectra(data,mdl)
        # mdl.scale(scale)
        # mdlnt.scale(scale)
        # splot.plotSpectrum(data,mdlnt,mdl,data-mdl,colors=['k','g','r','b'],legend=['Data','Model-Telluric','Best Model\nChi2={:.0f}'.format(best_chi),'Difference'],figsize=figsize,file=file+'_bestModel.pdf')
    
# burn off beginning of chain            
#    burned_parameters = parameters[int(burn*len(parameters)):]
#    burned_chis = chis[int(burn*len(chis)):]

#    if 'burn' in output.lower():
#        parameters = burned_parameters
#        chis = burned_chis


# correct for barycentric motion
#    if isinstance(vbary,u.quantity.Quantity):
#        vb = vbary.to(u.km/u.s).value
#    else:
#        vb = copy.deepcopy(vbary)
#    if 'rv' in list(param0.keys()):
#        final_parameters['rv'] = [r+vb for r in final_parameters['rv']]
#        best_parameters['rv']+=vb
#    if 'rv1' in list(param0.keys()):
#        final_parameters['rv1'] = [r+vb for r in final_parameters['rv1']]
#        best_parameters['rv1']+=vb
#    if 'rv2' in list(param0.keys()):
#        final_parameters['rv2'] = [r+vb for r in final_parameters['rv2']]
#        best_parameters['rv2']+=vb
        
# return values        
    if 'best' in output.lower():
        return best_parameters, best_chi
    else:
        return final_parameters, chis


def mcmcForwardModelReport(data,parameters,chis,burn=0.25,dof=0,plotChains=True,plotBest=True,plotMean=True,plotCorner=True,plotParameters=None,writeReport=True,vbary=0.,file='tmp',atm=None,model=None,model2=None,chiweights=False,binary=False,duplicate=False,verbose=True):
    '''
    :Purpose:

        Plotting and fit analysis routine for `mcmcForwardModelFit()`_

    :Required Inputs:

        :param data: Spectrum object containing the data modeled
        :param parameters: dictionary containing the parameters from the fit; each parameter should be linked to a array
        :param chis: list of the chi-square values (or equivalent statistic) that match the parameter arrays

    :Optional Inputs:

        :param: atm = None: Spectrum object containing the atmospheric/instrumental transmission profile (e.g., `loadTelluric()`_)
        :param: burn = 0.25: initial fraction of parameters to throw out ("burn-in")
        :param: dof = 0: degrees of freedom; if not provided, assumed to be the number of datapoints minus the number of varied parameters
        :param: binary = False: set to True if a binary model fit was done
        :param: duplicate = False: set to True if the secondary spectrum has same model parameters as primary
        :param: vbary = 0.: set to a velocity (assumed barycentric) to add to rv values
        :param: model = None: Spectrum object containing the primary spectral model; should be of higher resolution and wider wavelength range than the data
        :param: model2 = None: Spectrum object containing the secondary spectral model; should be of higher resolution and wider wavelength range than the data

        :param: plotParameters = None: array of the parameters to plot, which should be keys in teh parameters input dictionary; if None, all of the parameters are plot
        :param: plotChains = True: set to True to plot the parameter & chi-square value chains
        :param: plotBest = True: set to True to plot the best fit model
        :param: plotMean = True: set to True to plot the mean parameter model
        :param: plotCorner = True: set to True to plot a corner plot of parameters (requires corner.py package)
        :param: writeReport = True: set to True to write out best and average parameters to a file

        :param: chiweights = False: apply chi-square weighting for determining mean parameter values
        :param: file = 'tmp': file prefix for outputs; should include full path unless in operating in desired folder
        :param: verbose = False: provide extra feedback

        mcmcForwardModelReport() will also take as inputs the plotting parameters for `plotSpectrum()`_

    :Outputs:
        
        Depending on the flags set, various plots showing the derived parameters and best fit model for `mcmcForwardModelFit()`_

    :Example:

    >>> import splat
    >>> import splat.model as spmdl
    >>> import astropy.units as u
    >>> # read in spectrum
    >>> sp = splat.Spectrum('nirspec_spectrum.txt')
    >>> # read in and trim model
    >>> mdl = spmdl.loadModel(model='btsettl',teff=2600,logg=5.0,raw=True)
    >>> mdl.trim([numpy.min(sp.wave)-0.01*u.micron,numpy.max(sp.wave)+0.01*u.micron])
    >>> # read in and trim atmospheric absorption
    >>> atm = spmdl.loadTelluric(wave_range=[numpy.min(mdl.wave.value)-0.02,numpy.max(mdl.wave.value)+0.02],output='spec')
    >>> # inital parameters
    >>> mpar = {'rv': 0., 'vsini': 10., 'vinst': 5., 'alpha': 0.6}
    >>> mvar = {'rv': 1., 'vsini': 1., 'vinst': 0.2, 'alpha': 0.05}
    >>> mlim = {'vsini': [0.,500.], 'alpha': [0.,100.]}
    >>> # do fit
    >>> pars,chis = spmdl.mcmcForwardModelFit(sp,mdl,mpar,mvar,limits=mlim,atm=atm,nsteps=100,file='fit'')
    >>> # visualize results
    >>> spmdl.mcmcForwardModelReport(sp,mdl,pars,chis,file='fit',chiweights=True,plotParameters=['rv','vsini'])

    '''    
    par = copy.deepcopy(parameters)
    chi = copy.deepcopy(chis)
    nval = len(chis)

# burn first X% of chains
    if burn != 0. and burn < 1.:
        for k in list(par.keys()): par[k] = par[k][int(nval*burn):]
        chi = chi[int(nval*burn):]
        nval = len(chi)

# apply weighting function
    weights = numpy.ones(nval)
    if chiweights==True:
        if dof == 0: dof = int(len(data.wave)-len(list(par.keys())))
        weights = [stats.f.sf(c/numpy.nanmin(chi),dof,dof) for c in chi]
    weights = numpy.array(weights)
    weights=weights/numpy.nansum(weights)

# correct velocities for barycentric motion
    if isUnit(vbary):
        vb = vbary.to(u.km/u.s).value
    else:
        vb = copy.deepcopy(vbary)
    if 'rv' in list(par.keys()): par['rv'] = [r+vb for r in par['rv']]
    if 'rv1' in list(par.keys()): par['rv1'] = [r+vb for r in par['rv1']]
    if 'rv2' in list(par.keys()): 
        par['rv2'] = [r+vb for r in par['rv2']]
        par['rv1-rv2'] = numpy.array(par['rv1'])-numpy.array(par['rv2'])
        par['rv2-rv1'] = numpy.array(par['rv2'])-numpy.array(par['rv1'])

# best parameters
    i = numpy.argmin(chi)
    best_parameters = {}
    for k in list(par.keys()): best_parameters[k] = par[k][i]
    if verbose == True:
        print('\nBest Parameter Values:')
        for k in list(par.keys()): print('\t{} = {}'.format(k,best_parameters[k]))
        print('\tMinimum chi^2 = {}'.format(numpy.nanmin(chi)))
        
# mean parameters
    mean_parameters = {}
    mean_parameters_unc = {}
    for k in list(par.keys()):
        try:
            mean_parameters[k] = numpy.nansum(numpy.array(par[k])*weights)
            mean_parameters_unc[k] = numpy.sqrt(numpy.nansum((numpy.array(par[k])**2)*weights)-mean_parameters[k]**2)
        except:
            pass
    if verbose == True:
        print('\nMean Parameter Values:')
        for k in list(mean_parameters.keys()): print('\t{} = {}+/-{}'.format(k,mean_parameters[k],mean_parameters_unc[k]))

# prep plotting
    if plotParameters == None:
        plotParameters = list(mean_parameters.keys())
    toplot = {}
    for k in plotParameters: 
        if k in list(par.keys()): 
            if numpy.nanstd(par[k]) > 0.: 
                if k in list(mean_parameters.keys()):
                    if numpy.isfinite(mean_parameters_unc[k]): 
                        toplot[k] = par[k]
        else:
            print('\nWarning: parameter {} not in MCMC parameter list; ignoring'.format(k))

#    print(plotParameters,toplot.keys(),best_parameters.keys(),mean_parameters.keys())

# plot chains
    if plotChains==True:
        plt.clf()
        plt.figure(figsize=(6,3*(len(list(toplot.keys()))+1)))
        for i,k in enumerate(list(toplot.keys())):
            plt.subplot(len(list(toplot.keys()))+1,1,i+1)
            plt.plot(range(len(toplot[k])),toplot[k],'k-')
            plt.plot([0,len(toplot[k])],[best_parameters[k],best_parameters[k]],'b-')
            plt.plot([0,len(toplot[k])],[mean_parameters[k],mean_parameters[k]],'g--')
            plt.ylabel(str(k))  
            plt.xlim([0,len(toplot[k])])
        plt.subplot(len(list(toplot.keys()))+1,1,i+2)
        plt.plot(range(len(toplot[k])),chi)
        plt.ylabel(r'$\chi^2$')    
        plt.xlim([0,len(toplot[k])])
        plt.savefig(file+'_chains.pdf')

# plot corner
    if plotCorner==True:
        try:
            import corner
        except:
            print('\nYou must install corner to make corner plots: https://github.com/dfm/corner.py')
        else:
            plt.clf()
            pd = pandas.DataFrame(toplot)
            fig = corner.corner(pd, quantiles=[0.16, 0.5, 0.84], \
                labels=list(pd.columns), show_titles=True, weights=weights, \
                title_kwargs={"fontsize": 12})
            plt.savefig(file+'_corner.pdf')

# plot best model
    if plotBest==True:
        plt.clf()
        mdl,mdlnt = makeForwardModel(best_parameters,data,binary=binary,atm=atm,model=model,model2=model2,duplicate=duplicate,return_nontelluric=True)
        chi0,scale = splat.compareSpectra(data,mdl)
        mdl.scale(scale)
        mdlnt.scale(scale)
        splot.plotSpectrum(data,mdlnt,mdl,data-mdl,colors=['k','g','r','b'],legend=['Data','Model','Model x Telluric','Difference\nChi={:.0f}'.format(chi0)],figsize=[15,5],file=file+'_bestModel.pdf')

# plot mean model
    if plotMean==True:
        plt.clf()
        mdl,mdlnt = makeForwardModel(mean_parameters,data,binary=binary,atm=atm,model=model,model2=model2,duplicate=duplicate,return_nontelluric=True)
        chi0,scale = splat.compareSpectra(data,mdl)
        mdl.scale(scale)
        mdlnt.scale(scale)
        splot.plotSpectrum(data,mdlnt,mdl,data-mdl,colors=['k','g','r','b'],legend=['Data','Model','Model x Telluric','Difference\nChi={:.0f}'.format(chi0)],figsize=[15,5],file=file+'_meanModel.pdf')

# summarize results to a text file
    if writeReport==True:
        f = open(file+'_report.txt','w')
        f.write('Last Parameter Values:')
        for k in list(par.keys()): f.write('\n\t{} = {}'.format(k,par[k][-1]))
        f.write('\n\tchi^2 = {}'.format(chi[-1]))
        f.write('\n\nBest Parameter Values:')
        for k in list(best_parameters.keys()): f.write('\n\t{} = {}'.format(k,best_parameters[k]))
        f.write('\n\tchi^2 = {}'.format(numpy.nanmin(chi)))
        f.write('\n\nMean Parameter Values:')
        for k in list(mean_parameters.keys()): f.write('\n\t{} = {}+/-{}'.format(k,mean_parameters[k],mean_parameters_unc[k]))
        f.close()        

    return        


def _smooth2resolution(wave,flux,resolution,**kwargs):
    method = kwargs.get('method','hamming')
    overscale = kwargs.get('overscale',11)

    r = resolution*overscale
    npix = numpy.floor(numpy.log(numpy.nanmax(wave)/numpy.nanmin(wave))/numpy.log(1.+1./r))
    wave_sample = [numpy.nanmin(wave)*(1.+1./r)**i for i in numpy.arange(npix)]
    f = interp1d(wave,flux,bounds_error=False,fill_value=0.)
    flx_sample = f(wave_sample)
    window = signal.get_window(method,numpy.round(overscale))
    flxsm = signal.convolve(flx_sample, window/numpy.sum(window), mode='same')
    f = interp1d(wave_sample,flxsm,bounds_error=False,fill_value=0.)
    return f(wave)




def loadModel(modelset='btsettl08',instrument='SPEX-PRISM',raw=False,sed=False,*args,**kwargs):
    '''
    Purpose: 
        Loads up a model spectrum based on a set of input parameters. The models may be any one of the following listed below. For parameters between the model grid points, loadModel calls the function `_loadInterpolatedModel()`_.

    .. _`_loadInterpolatedModel()` : api.html#splat_model._loadInterpolatedModel

    Required Inputs:
        :param: **model**: The model set to use; may be one of the following:

            - *nextgen99*: model set from `Allard et al. (1999) <http://adsabs.harvard.edu/abs/2012RSPTA.370.2765A>`_  with effective temperatures of 900 to 1600 K (steps of 100 K); surface gravities of 5.0 and 5.5 in units of cm/s^2; and metallicity fixed to solar (alternate designations: `nextgen`)
            - *cond01*: model set from `Allard et al. (2001) <http://adsabs.harvard.edu/abs/2001ApJ...556..357A>`_  with effective temperatures of 100 to 4000 K (steps of 100 K); surface gravities of 4.0 to 6.0 in units of cm/s^2 (steps of 0.5 dex); and metallicity fixed to solar; with condensate species removed from the photosphere (alternate designation: `cond`)
            - *dusty01*: model set from `Allard et al. (2001) <http://adsabs.harvard.edu/abs/2001ApJ...556..357A>`_  with effective temperatures of 500 to 3000 K (steps of 100 K); surface gravities of 3.5 to 6.0 in units of cm/s^2 (steps of 0.5 dex); and metallicity fixed to solar; with condensate species left in situ (alternate designation: `dusty`)
            - *burrows06*: model set from `Burrows et al. (2006) <http://adsabs.harvard.edu/abs/2006ApJ...640.1063B>`_ with effective temperatures of 700 to 2000 K (steps of 50 K); surface gravities of 4.5 to 5.5 in units of cm/s^2 (steps of 0.1 dex); metallicity of -0.5, 0.0 and 0.5; and either no clouds or grain size 100 microns (fsed = 'nc' or 'f100'). equilibrium chemistry is assumed. Note that this grid is not completely filled and some gaps have been interpolated (alternate designations: `burrows`, `burrows2006`)
            - *btsettl08*: (default) model set from `Allard et al. (2012) <http://adsabs.harvard.edu/abs/2012RSPTA.370.2765A>`_  with effective temperatures of 400 to 2900 K (steps of 100 K); surface gravities of 3.5 to 5.5 in units of cm/s^2 (steps of 0.5 dex); and metallicity of -3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.3, and 0.5 for temperatures greater than 2000 K only; cloud opacity is fixed in this model, and equilibrium chemistry is assumed. Note that this grid is not completely filled and some gaps have been interpolated (alternate designations: `btsettled`, `btsettl`, `allard`, `allard12`)
            - *btsettl15*: model set from `Allard et al. (2015) <http://adsabs.harvard.edu/abs/2015A&A...577A..42B>`_  with effective temperatures of 1200 to 6300 K (steps of 100 K); surface gravities of 2.5 to 5.5 in units of cm/s^2 (steps of 0.5 dex); and metallicity fixed to solar (alternate designations: 'allard15','allard2015','btsettl015','btsettl2015','BTSettl2015')
            - *morley12*: model set from `Morley et al. (2012) <http://adsabs.harvard.edu/abs/2012ApJ...756..172M>`_ with effective temperatures of 400 to 1300 K (steps of 50 K); surface gravities of 4.0 to 5.5 in units of cm/s^2 (steps of 0.5 dex); and sedimentation efficiency (fsed) of 2, 3, 4 or 5; metallicity is fixed to solar, equilibrium chemistry is assumed, and there are no clouds associated with this model (alternate designations: `morley2012`)
            - *morley14*: model set from `Morley et al. (2014) <http://adsabs.harvard.edu/abs/2014ApJ...787...78M>`_ with effective temperatures of 200 to 450 K (steps of 25 K) and surface gravities of 3.0 to 5.0 in units of cm/s^2 (steps of 0.5 dex); metallicity is fixed to solar, equilibrium chemistry is assumed, sedimentation efficiency is fixed at fsed = 5, and cloud coverage fixed at 50% (alternate designations: `morley2014`)
            - *saumon12*: model set from `Saumon et al. (2012) <http://adsabs.harvard.edu/abs/2012ApJ...750...74S>`_ with effective temperatures of 400 to 1500 K (steps of 50 K); and surface gravities of 3.0 to 5.5 in units of cm/s^2 (steps of 0.5 dex); metallicity is fixed to solar, equilibrium chemistry is assumed, and no clouds are associated with these models (alternate designations: `saumon`, `saumon2012`)
            - *drift*: model set from `Witte et al. (2011) <http://adsabs.harvard.edu/abs/2011A%26A...529A..44W>`_ with effective temperatures of 1700 to 3000 K (steps of 50 K); surface gravities of 5.0 and 5.5 in units of cm/s^2; and metallicities of -3.0 to 0.0 (in steps of 0.5 dex); cloud opacity is fixed in this model, equilibrium chemistry is assumed (alternate designations: `witte`, `witte2011`, `helling`)
            - *madhusudhan11*: model set from `Madhusudhan et al. (2011) <http://adsabs.harvard.edu/abs/2011ApJ...737...34M>`_ with effective temperatures of 600 K to 1700 K (steps of 50-100 K); surface gravities of 3.5 and 5.0 in units of cm/s^2; and metallicities of 0.0 to 1.0 (in steps of 0.5 dex); there are multiple cloud prescriptions for this model, equilibrium chemistry is assumed (alternate designations: `madhusudhan`)
        
    Optional Inputs:
        :param: **teff**: effective temperature of the model in K (e.g. `teff` = 1000)
        :param: **logg**: log10 of the surface gravity of the model in cm/s^2 units (e.g. `logg` = 5.0)
        :param: **z**: log10 of metallicity of the model relative to solar metallicity (e.g. `z` = -0.5)
        :param: **fsed**: sedimentation efficiency of the model (e.g. `fsed` = 'f2')
        :param: **cld**: cloud shape function of the model (e.g. `cld` = 'f50')
        :param: **kzz**: vertical eddy diffusion coefficient of the model (e.g. `kzz` = 2)
        :param: **slit**: slit weight of the model in arcseconds (e.g. `slit` = 0.3)
        :param: **sed**: if set to True, returns a broad-band spectrum spanning 0.3-30 micron (applies only for BTSettl2008 models with Teff < 2000 K)

        :param: **folder**: string of the folder name containing the model set (default = '')
        :param: **filename**: string of the filename of the desired model; should be a space-delimited file containing columns for wavelength (units of microns) and surface flux (F_lambda units of erg/cm^2/s/micron) (default = '')
        :param: **force**: force the filename to be exactly as specified
        :param: **fast**: set to True to do a fast interpolation if needed, only for Teff and logg (default = False)
        :param: **url**: string of the url to the SPLAT website (default = 'http://www.browndwarfs.org/splat/')

    Output:
        A SPLAT Spectrum object of the interpolated model with wavelength in microns and surface fluxes in F_lambda units of erg/cm^2/s/micron.

    Example:

    >>> import splat
    >>> mdl = splat.loadModel(teff=1000,logg=5.0)
    >>> mdl.info()
        BTSettl2008 model with the following parmeters:
        Teff = 1000 K
        logg = 5.0 cm/s2
        z = 0.0
        fsed = nc
        cld = nc
        kzz = eq
        Smoothed to slit width 0.5 arcseconds
    >>> mdl = splat.loadModel(teff=2500,logg=5.0,model='burrows')
        Input value for teff = 2500 out of range for model set burrows06
        Warning: Creating an empty Spectrum object
    '''


# path to model and set local/online
# by default assume models come from local SPLAT directory

#   REMOVED 10/19/2017
#    local = kwargs.get('local',True)
#    online = kwargs.get('online',not local and not checkOnline())
#    local = not online
#    kwargs['local'] = local
#    kwargs['online'] = online
#    kwargs['url']  = kwargs.get('url',SPLAT_URL)
    kwargs['ismodel'] = True
    kwargs['force'] = kwargs.get('force',False)
    kwargs['folder'] = kwargs.get('folder','./')
    runfast = kwargs.get('runfast',False)
    verbose = kwargs.get('verbose',False)


# has a filename been passed? check first if it is a model set name
# otherwise assume this file is a local file
# and check that the path is correct if its fully provided
# otherwise assume path is inside provided folder keyword
    if len(args) > 0:
        mset = checkSpectralModelName(args[0])
        if mset != False: modelset=mset
        else:
            kwargs['filename'] = os.path.normpath(args[0])
            if not os.path.exists(kwargs['filename']):
                kwargs['filename'] = os.path.normpath(kwargs['folder']+os.path.basename(kwargs['filename']))
                if not os.path.exists(kwargs['filename']):
                    raise NameError('\nCould not find model file {} or {}'.format(kwargs['filename'],kwargs['folder']+os.path.basename(kwargs['filename'])))

# check if already read in
            if kwargs['filename'] in list(MODELS_READIN.keys()) and runfast == True:
#            if verbose: print('RUNFAST 1: {}'.format(kwargs['filename']))
                return MODELS_READIN[kwargs['filename']]
            else:
                MODELS_READIN[kwargs['filename']] = Spectrum(**kwargs)
                return MODELS_READIN[kwargs['filename']]


# set up the model set
#    modelset = kwargs.get('model','BTSettl2008')
    modelset = kwargs.get('model',modelset)
    modelset = kwargs.get('set',modelset)
    mset = checkSpectralModelName(modelset)
    if mset == False: raise ValueError('Could not find model set {}; possible options are {}'.format(modelset,list(SPECTRAL_MODELS.keys())))
    kwargs['modelset'] = mset

#    kwargs['instrument'] = kwargs.get('instrument','SPEX-PRISM')
    instrument = kwargs.get('instr',instrument)
    if raw == True: instrument = 'RAW'
    if sed == True: instrument = 'SED'
    inst = checkInstrument(instrument)
    if inst != False: instrument = inst
    if instrument not in list(SPECTRAL_MODELS[mset]['instruments'].keys()):
        raise ValueError('Models for set {} and instrument {} have not yet been computed; run processModelsToInstrument()'.format(kwargs['modelset'],instrument))
    kwargs['instrument'] = instrument
    kwargs['name'] = kwargs['modelset']+' ('+kwargs['instrument']+')'


# check that model data is available
#    kwargs['folder'] = kwargs.get('folder',os.path.normpath(SPECTRAL_MODELS[kwargs['model']]['folder']+'/'+kwargs['instrument']+'/'))
    kwargs['folder'] = os.path.normpath(SPECTRAL_MODELS[kwargs['modelset']]['instruments'][kwargs['instrument']])
    if not os.path.exists(kwargs['folder']):
        finit = kwargs['folder']
        kwargs['folder'] = os.path.normpath(SPLAT_PATH+SPECTRAL_MODEL_FOLDER+kwargs['modelset']+'/'+kwargs['instrument']+'/')
        if not os.path.exists(kwargs['folder']):
            raise ValueError('\nCould not locate folder {} or {} for model {} and instrument {}; make sure models are properly located'.format(finit,kwargs['folder'],kwargs['modelset'],kwargs['instrument']))

# preset defaults
    mparam = {}
    for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
        if ms in list(SPECTRAL_MODELS[kwargs['modelset']]['default'].keys()):
            mparam[ms] = kwargs.get(ms,SPECTRAL_MODELS[kwargs['modelset']]['default'][ms])
            if isUnit(mparam[ms]):
                mparam[ms] = (mparam[ms].to(SPECTRAL_MODEL_PARAMETERS[ms]['unit'])).value
    if len(mparam.keys()) == 0:
        raise ValueError('\nDid not have any parameters to set; this is a error in the program')
    for ms in mparam.keys(): kwargs[ms] = mparam[ms]

# generate model filename
    
    filename = os.path.join(SPECTRAL_MODELS[kwargs['modelset']]['instruments'][kwargs['instrument']],kwargs['modelset'])

    for k in SPECTRAL_MODEL_PARAMETERS_INORDER:
        if k in list(SPECTRAL_MODELS[kwargs['modelset']]['default'].keys()):
            if k in list(mparam.keys()): val = mparam[k] 
            else: val = SPECTRAL_MODELS[mset]['default'][k]
            if SPECTRAL_MODEL_PARAMETERS[k]['type'] == 'continuous':
                kstr = '_{}{:.2f}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],float(val))
            else:
                kstr = '_{}{}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],val)
            if k == 'teff': kstr = '_{}{}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],int(val))
            elif k == 'z': kstr = '_{}{:.2f}'.format(SPECTRAL_MODEL_PARAMETERS[k]['prefix'],float(val)-0.0001)
            filename=filename+kstr
    kwargs['filename'] = filename+'_{}.txt'.format(kwargs['instrument'])

#    kwargs['filename'] = os.path.normpath(kwargs['folder'])+'{}_{:.0f}_{:.1f}_{:.1f}_{}_{}_{}_{}.txt'.\
#        format(kwargs['model'],float(kwargs['teff']),float(kwargs['logg']),float(kwargs['z'])-0.001,kwargs['fsed'],kwargs['cld'],kwargs['kzz'],kwargs['instrument']))

#    if kwargs.get('sed',False):
#        kwargs['filename'] = kwargs['folder']+kwargs['model']+'_{:.0f}_{:.1f}_{:.1f}_nc_nc_eq_sed.txt'.\
#            format(float(kwargs['teff']),float(kwargs['logg']),float(kwargs['z'])-0.001)

# get model parameters
#        parameters = loadModelParameters(**kwargs)
#        kwargs['path'] = kwargs.get('path',parameters['path'])
# check that given parameters are in range
#        for ms in MODEL_PARAMETER_NAMES[0:3]:
#            if (float(kwargs[ms]) < parameters[ms][0] or float(kwargs[ms]) > parameters[ms][1]):
#                raise NameError('\n\nInput value for {} = {} out of range for model set {}\n'.format(ms,kwargs[ms],kwargs['set']))
#        for ms in MODEL_PARAMETER_NAMES[3:6]:
#            if (kwargs[ms] not in parameters[ms]):
#                raise NameError('\n\nInput value for {} = {} not one of the options for model set {}\n'.format(ms,kwargs[ms],kwargs['set']))


# have we already read in? if so just return saved spectrum object
    if kwargs['filename'] in list(MODELS_READIN.keys()):
#        if verbose: print('RUNFAST 2: {}'.format(kwargs['filename']))
        return MODELS_READIN[kwargs['filename']]


# check that folder/set is present either locally or online
# if not present locally but present online, switch to this mode
# if not present at either raise error

# REMOVED THIS 8/30/2017

#    folder = checkLocal(kwargs['folder'])
#    if folder=='':
#        folder = checkOnline(kwargs['folder'])
#        if folder=='':
#            print('\nCould not find '+kwargs['folder']+' locally or on SPLAT website')
#            print('\nAvailable model set options are:')
#            for s in DEFINED_MODEL_SET:
#                print('\t{}'.format(s))
#            raise NameError()
#        else:
#            kwargs['folder'] = folder
#            kwargs['local'] = False
#            kwargs['online'] = True
#    else:
#        kwargs['folder'] = folder

# check if file is present; if so, read it in, otherwise go to interpolated
# locally:
#    if kwargs.get('local',True) == True:
    file = checkLocal(kwargs['filename'])
    if file=='':
        file = checkLocal(kwargs['filename']+'.gz')
        if file=='':
            if kwargs['force']: raise NameError('\nCould not find '+kwargs['filename']+' locally\n\n')
            else: sp = _loadInterpolatedModel(**kwargs)
        else: kwargs['filename'] = kwargs['filename']+'.gz'
#                kwargs['local']=False
#                kwargs['online']=True
#        else:
#    else:
    if file != '':
        sp = Spectrum(**kwargs)
        MODELS_READIN[kwargs['filename']] = sp

# populate model parameters
    setattr(sp,'modelset',kwargs['modelset'])
    setattr(sp,'instrument',kwargs['instrument'])
    for k in list(SPECTRAL_MODELS[kwargs['modelset']]['default'].keys()):
        if k in list(mparam.keys()): setattr(sp,k,mparam[k])
        else: setattr(sp,k,SPECTRAL_MODELS[mset]['default'][k])

# online:
#   REMOVED 10/19/2017
#    if kwargs['online'] == True:
#        file = checkOnline(kwargs['filename'])
#        if file=='':
#            file = checkLocal(kwargs['filename']+'.gz')
#            if file=='':
#                if kwargs['force']: raise NameError('\nCould not find '+kwargs['filename']+' online\n\n')
#                else: sp = _loadInterpolatedModel(**kwargs)
#            else: kwargs['filename'] = kwargs['filename']+'.gz'
#
#        ftype = kwargs['filename'].split('.')[-1]
#        if ftype == '.gz': ftype = kwargs['filename'].split('.')[-2]+'.gz'
#        tmp = TMPFILENAME+'.'+ftype
#        open(os.path.basename(tmp), 'wb').write(requests.get(url+kwargs['filename']).content) 
#        mkwargs = copy.deepcopy(kwargs)
#        mkwargs['filename'] = os.path.basename(tmp)
#        sp = Spectrum(**mkwargs)
#        os.remove(os.path.basename(tmp))

# add to read in files
    
    return sp


def getModel(*args, **kwargs):
    '''
    Purpose: 
        Redundant routine with `loadModel()`_ to match syntax of `getSpectrum()`_

    .. _`loadModel()` : api.html#splat_model.loadModel
    .. _`getSpectrum()` : api.html#splat.getSpectrum

    '''
    return loadModel(*args, **kwargs)


def _checkModelParametersInRange(mparam):
# list of model parameters provided
    mp = list(mparam.keys())
    if 'model' not in mp:
        mparam['model'] = 'BTSettl2008'
    if 'instrument' not in mp:
        mparam['instrument'] = 'SPEX-PRISM'
    parameters = _loadModelParameters(**mparam)
    flag = True

# check that given parameters are in model ranges
    for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
        if SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'continuous':
#            ms=='teff' or ms=='logg' or ms=='z':
            if ms in mp:
                if (float(mparam[ms]) < numpy.min(parameters[ms]) or float(mparam[ms]) > numpy.max(parameters[ms])):
                    print('\n\nInput value for {} = {} out of range for model set {}\n'.format(ms,mparam[ms],mparam['model']))
                    flag = False
        else:
            if ms in mp:
                if (mparam[ms] not in parameters[ms]):
                    print('\n\nInput value for {} = {} not one of the options for model set {}\n'.format(ms,mparam[ms],mparam['model']))
                    flag = False
    return flag


def _loadInterpolatedModel(*args,**kwargs):
    '''
    Purpose: 
        Generates as spectral model with is interpolated between model parameter grid points. This routine is called by `loadModel()`_, or it can be called on its own.

    .. _`loadModel()` : api.html#splat_model.loadModel

    Required Inputs:
        :param model: set of models to use; see options in `loadModel()`_

    Optional Inputs:
        :param: The parameters for `loadModel()`_ can also be used here.

    Output:
        A SPLAT Spectrum object of the interpolated model with wavelength in microns and surfae fluxes in F_lambda units of erg/cm^2/s/micron.

    Example:

    >>> import splat.model as spmdl
    >>> mdl = spmdl.loadModel(teff=1000,logg=5.0)
    >>> mdl.info()
        BT-Settl (2008) Teff=1000 logg=5.0 [M/H]=0.0 atmosphere model with the following parmeters:
        Teff = 1000 K
        logg = 5.0 dex
        z = 0.0 dex
        fsed = nc
        cld = nc
        kzz = eq

        If you use this model, please cite Allard, F. et al. (2012, Philosophical Transactions of the Royal Society A, 370, 2765-2777)
        bibcode = 2012RSPTA.370.2765A
    '''
# attempt to generalize models to extra dimensions
    mkwargs = kwargs.copy()
    mkwargs['force'] = True
#    mkwargs['local'] = kwargs.get('local',True)

# set up the model set
#    mkwargs['model'] = mkwargs.get('model','BTSettl2008')
#    mkwargs['model'] = mkwargs.get('modelset',mkwargs['model'])
#    mkwargs['model'] = mkwargs.get('set',mkwargs['model'])
#    mkwargs['model'] = checkSpectralModelName(mkwargs['model'])
#    mkwargs['instrument'] = mkwargs.get('instrument','SPEX_PRISM')
#    mkwargs['instrument'] = checkInstrument(mkwargs['instrument'])
#    mkwargs['name'] = mkwargs['model']
    
#    mkwargs['folder'] = SPLAT_PATH+SPECTRAL_MODEL_FOLDER+mkwargs['model']+'/'


#    for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
#        mkwargs[ms] = kwargs.get(ms,SPECTRAL_MODEL_PARAMETERS[ms]['default'])

# some special defaults
#    if mkwargs['model'] == 'morley12':
#        if mkwargs['fsed'] == 'nc':
#            mkwargs['fsed'] = 'f2'
#    if mkwargs['model'] == 'morley14':
#        if mkwargs['fsed'] == 'nc':
#            mkwargs['fsed'] = 'f5'
#        if mkwargs['cld'] == 'nc':
#            mkwargs['cld'] = 'f50'

# first get model parameters
    if _checkModelParametersInRange(mkwargs) == False:
        raise ValueError('\n\nModel parameter values out of range for model set {}\n'.format(mkwargs['model']))
    
# check that given parameters are in range - RETHINK THIS
#    for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
#        if ms=='teff' or ms =='logg' or ms=='z':
#            if (float(mkwargs[ms]) < numpy.min(parameters[ms]) or float(mkwargs[ms]) > numpy.max(parameters[ms])):
#                raise ValueError('\n\nInput value for {} = {} out of range for model set {}\n'.format(ms,mkwargs[ms],mkwargs['model']))
#        else:
#            if (mkwargs[ms] not in parameters[ms]):
#                raise ValueError('\n\nInput value for {} = {} not one of the options for model set {}\n'.format(ms,mkwargs[ms],mkwargs['model']))



# FAST METHOD - just calculate a simple weight factor that linearly interpolates between grid points (all logarithmic)

    if kwargs.get('fast',True) == True:
        parameters = _loadModelParameters(mkwargs['model'],mkwargs['instrument'],pandas=True)
        mparams = {}
        mweights = {}
        mgrid = []
        pgrid = []
        plin = []
        for ms in list(SPECTRAL_MODEL_PARAMETERS.keys()):
            if ms in list(parameters.keys()):
                if SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'discrete': 
                    mparams[ms] = mkwargs[ms]
                    mweights[ms] = 1.
                    plin.append(ms)
                else:
                    l = parameters[parameters[ms] <= float(mkwargs[ms])].sort_values(ms)[ms].iloc[-1]
                    h = parameters[parameters[ms] >= float(mkwargs[ms])].sort_values(ms)[ms].iloc[0]
                    if ms == 'teff':
                        d = numpy.log10(h)-numpy.log10(l)
                        w = (numpy.log10(h)-numpy.log10(float(mkwargs[ms])))/d
                    else:
                        d = h-l
                        w = (h-float(mkwargs[ms]))/d
                    if d == 0.: w = 0.5
                    mparams[ms] = [l,h]
                    mweights[ms] = w
                    mgrid.append([l,h])
                    pgrid.append(ms)

# generate all possible combinations - doing this tediously due to concerns over ordering
        x = numpy.meshgrid(*mgrid)
        a = {}
        weights = numpy.ones(len(x[0].flatten()))
        for i,ms in enumerate(pgrid): 
            a[ms] = x[i].flatten()
            for j,v in enumerate(a[ms]):
                if v == mparams[ms][0]:
                    weights[j] *= mweights[ms]
                else:
                    weights[j] *= (1.-mweights[ms])

# read in models
        models = []
        for i in numpy.arange(len(weights)):
            mparam = copy.deepcopy(mkwargs)
            for ms in list(SPECTRAL_MODEL_PARAMETERS.keys()):
                if ms in list(parameters.keys()):
                    if SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'discrete': 
                        mparam[ms] = mkwargs[ms]
                    else:
                        mparam[ms] = a[ms][i]
            del mparam['filename']
            models.append(loadModel(**mparam))

# create interpolation
        mflx = []
        for i,w in enumerate(models[0].wave):
            val = numpy.array([numpy.log10(m.flux.value[i]) for m in models])
            mflx.append(10.**(numpy.sum(val*weights)/numpy.sum(weights)))


# REGULAR METHOD - uses meshgrid & griddata - about 4x slower
    else:

# identify grid points around input parameters
# 3x3 grid for teff, logg, z
        parameters = _loadModelParameters(mkwargs['model'],mkwargs['instrument'])

        tvals = numpy.array([float(p['teff']) for p in parameters['parameter_sets']])
        gvals = numpy.array([float(p['logg']) for p in parameters['parameter_sets']])
        zvals = numpy.array([float(p['z']) for p in parameters['parameter_sets']])
        tdiff = numpy.array([numpy.log10(float(mkwargs['teff']))-numpy.log10(v) for v in tvals])
        gdiff = numpy.array([float(mkwargs['logg'])-v for v in gvals])
        zdiff = numpy.array([float(mkwargs['z'])-v for v in zvals])
        dist = tdiff**2+gdiff**2+zdiff**2

# get closest models in 8 quadrant points
        mparams = []
#    mparam_names = []
        psets = numpy.array(parameters['parameter_sets'])
        for i in numpy.arange(0,2):
            dt = dist[numpy.where(tdiff*((-1)**i)>=0)]
            pt = psets[numpy.where(tdiff*((-1)**i)>=0)]
            gt = gdiff[numpy.where(tdiff*((-1)**i)>=0)]
            zt = numpy.round(zdiff[numpy.where(tdiff*((-1)**i)>=0)]*50.)/50.
            for j in numpy.arange(0,2):
                dg = dt[numpy.where(gt*((-1)**j)>=0)]
                pg = pt[numpy.where(gt*((-1)**j)>=0)]
                zg = zt[numpy.where(gt*((-1)**j)>=0)]
                for k in numpy.arange(0,2):
                    dz = dg[numpy.where(zg*((-1)**k)>=0)]
                    pz = pg[numpy.where(zg*((-1)**k)>=0)]

# if we can't get a quadrant point, quit out
                    if len(pz) == 0: 
#                    print(i,j,k)
#                    print(pg)
#                    print(zg)
#                    print(zg)
                        raise ValueError('\n\nModel parameter values out of range for model set {}\n'.format(mkwargs['model']))

                    pcorner = pz[numpy.argmin(dz)]
                    mparams.append(pz[numpy.argmin(dz)])

# generate meshgrid with slight offset and temperature on log scale
        rng = []
        for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
            if ms=='teff' or ms =='logg' or ms=='z':
                vals = [float(m[ms]) for m in mparams]
                r = [numpy.min(vals),numpy.max(vals)]
                if numpy.absolute(r[0]-r[1]) < 1.e-3*numpy.absolute(parameters[ms][1]-parameters[ms][0]):
                    r[1] = r[0]+1.e-3*numpy.absolute(parameters[ms][1]-parameters[ms][0])
                if ms == 'teff':
                    r = numpy.log10(r)
                rng.append(r)
        mx,my,mz = numpy.meshgrid(rng[0],rng[1],rng[2])

# read in unique models
        bmodels = {}
        models = []
        mp = copy.deepcopy(mparams[0])
        for i in numpy.arange(len(mx.flatten())):
            mp['teff'] = int(numpy.round(10.**(mx.flatten()[i])))
            mp['logg'] = my.flatten()[i]
            mp['z'] = mz.flatten()[i]
            mstr = '{:d}{:.1f}{:.1f}'.format(mp['teff'],mp['logg'],mp['z'])
            if mstr not in list(bmodels.keys()):
                bmodels[mstr] = loadModel(instrument=mkwargs['instrument'],force=True,**mp)
            models.append(bmodels[mstr])


#    mpsmall = [dict(y) for y in set(tuple(x.items()) for x in mparams)]
#    mpsmall = numpy.unique(numpy.array(mparams))
#    bmodels = []
#    bmodel_names = []
#    for m in mpsmall:
#        bmodels.append(loadModel(instrument=mkwargs['instrument'],force=True,**m))
#        mstr = ''
#        for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: mstr+=str(m[ms])
#        bmodel_names.append(mstr)
#        if kwargs.get('verbose',False): print(m)
#    bmodels = numpy.array(bmodels)
#    bmodel_names = numpy.array(bmodel_names)

# now set up model array in mx,my,mz order
#    mparam_names = []
#    models = []
#    for i,m in enumerate(mparam_names):
#    for i in numpy.arange(len(mx.flatten())):
#        mstr = '{:d}{:.1f}{:.1f}'.format(mx.flatten()[i],my.flatten()[i],mz.flatten()[i])
#        for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: mstr+=str(mparams[-1][ms])
#        models.append(bmodels[numpy.where(bmodel_names==m)][0])
#        mparam_names.append(mstr)

#    models = []
#    for i,m in enumerate(mparam_names):
#        models.append(bmodels[numpy.where(bmodel_names==m)][0])

        if kwargs.get('debug',False):
            print(mx.flatten())
            print([m.teff for m in models])
            print(my.flatten())
            print([m.logg for m in models])
            print(mz.flatten())
            print([m.z for m in models])
#        print(mparams)
#        print(mparam_names)


# final interpolation
        mflx = []
        for i,w in enumerate(models[0].wave):
            val = numpy.array([numpy.log10(m.flux.value[i]) for m in models])
            mflx.append(10.**(griddata((mx.flatten(),my.flatten(),mz.flatten()),\
                val,(numpy.log10(float(mkwargs['teff'])),float(mkwargs['logg']),float(mkwargs['z'])),'linear')))

    return Spectrum(wave=models[0].wave,flux=mflx*models[0].funit,**mkwargs)




def _loadModelParameters(*args,**kwargs):
    '''
    Purpose: 
        Assistant routine for `loadModel()`_ that loads in the spectral model grid points.

    .. _`loadModel()` : api.html#splat_model.loadModel

    Required Inputs:
        :param: model: set of models to use; see options in `loadModel()`_ (default = 'BTSettl2008')
    
    Optional Inputs:
        **instrument = 'RAW'**: search specifically for an instrument-designed model 
        **pandas = False**: return a pandas Dataframe


    The parameters for `loadModel()`_ can also be used here.

    Output:
        A dictionary containing the individual parameter values for the grid points in the given model set (not all of these grid points will be filled); this dictionary includs a list of dictionaries containing the individual parameter sets.
    '''

# model set
    modelset = False
    if len(args) > 0: modelset = args[0]
    modelset = kwargs.get('modelset',modelset)
    modelset = kwargs.get('model',modelset)
    modelset = kwargs.get('set',modelset)
    mset = checkSpectralModelName(modelset)
    if mset == False:
        raise NameError('\nInput model set {} not in defined set of models:\n{}\n'.format(modelset,list(SPECTRAL_MODELS.keys())))

# instrument
    instrument = ''
    if len(args) > 1: instrument = args[1]
    instrument = kwargs.get('instrument',instrument)
    instrument = kwargs.get('instr',instrument)
    instr = checkInstrument(instrument)
    if instr != False: instrument = instr
    if instrument not in list(SPECTRAL_MODELS[mset]['instruments'].keys()):
        ins = list(SPECTRAL_MODELS[mset]['instruments'].keys())
        if 'ORIGINAL' in ins: ins.remove('ORIGINAL')
        if len(ins) == 0: raise ValueError('\nNo SPLAT-processed models for {}'.format(mset))
        instrument = ins[0]

# folder for models
    mfolder = os.path.normpath(SPECTRAL_MODELS[mset]['instruments'][instrument])
    if not os.access(mfolder, os.R_OK):
#        raise NameError('\nInstrument setting {} is not defined for model set {}\n'.format(instrument,mset))
#        mfolder = os.path.normpath(SPLAT_PATH+SPECTRAL_MODEL_FOLDER+'/'+mset)
#        if not os.access(mfolder, os.R_OK):
        raise OSError('\nCould not find model folder {}\n'.format(mfolder))

    parameters = {'model': mset, 'instrument': instrument, 'parameter_sets': []}
    for ms in list(SPECTRAL_MODELS[mset]['default'].keys()):
        parameters[ms] = []
#    print(parameters.keys())

# establish parameters from list of filenames
#    if kwargs.get('old',False) == False:
    mfiles = glob.glob(mfolder+'/*.txt')
    if instr == 'RAW' or len(mfiles) == 0: mfiles = glob.glob(mfolder+'/*.gz')
    if len(mfiles) == 0:
        raise ValueError('\nCould not find any model files in {}'.format(mfolder))
    for mf in mfiles:
        p = {'model': mset, 'instrument': instrument}
        sp = numpy.array(os.path.basename(mf).replace('.txt','').replace('.gz','').replace(mset+'_','').replace('_'+instrument,'').split('_'))
        if '' in sp: 
            sp = list(sp)
            sp.remove('')
            sp = numpy.array(sp)
        for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
            if ms in list(parameters.keys()):
#                print(mf,sp,ms)
                val = sp[[SPECTRAL_MODEL_PARAMETERS[ms]['prefix'] in l for l in sp]][0][len(SPECTRAL_MODEL_PARAMETERS[ms]['prefix']):]
                if SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'continuous': val = float(val)
                parameters[ms].append(val)
                p[ms] = val
        parameters['parameter_sets'].append(p)

#        if len(sp) >= len(SPECTRAL_MODEL_PARAMETERS_INORDER):
#            p = {'model': mset}
#            for i,ms in enumerate(SPECTRAL_MODEL_PARAMETERS_INORDER):
#                if sp[i] not in parameters[ms]:
#                    parameters[ms].append(sp[i])
#                p[ms] = sp[i]
#            parameters['parameter_sets'].append(p)
    for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
#        if ms=='teff' or ms =='logg' or ms=='z':
#            parameters[ms] = [float(x) for x in parameters[ms]]
        if ms in list(parameters.keys()):
            parameters[ms].sort()
            parameters[ms] = numpy.array(parameters[ms])

#    print(parameters.keys(),parameters)

    if kwargs.get('pandas',False) == True:
        dp = pandas.DataFrame(parameters['parameter_sets'])
 #       for ms in ['teff','logg','z']: dp[ms] = [float(t) for t in dp[ms]]
        return dp
    else:
        return parameters



def loadTelluric(wave_range=None,ndata=None,linear=True,log=False,output='transmission',folder=splat.SPLAT_PATH+'/reference/SolAtlas/',*args):
    '''
    Purpose: 

        Loads up telluric absorption spectrum from `Livingston and Wallace (1991) <http://adsabs.harvard.edu/abs/1991aass.book.....L>`_

    Required Inputs:

        A wavelength array must be input in one of the following manners:

            - as an list passed as an argument ``wave``; e.g., loadTelluric(wave)
            - by specifying the min and max wavelengths with ``wave_range`` and number of points with ``ndata``; e.g., loadTelluric(wave_range=[1.3,1.5],ndata=100)

    Optional Inputs:

        :param: **linear**: linear sampling over ``wave_range`` (default = True)
        :param: **log**: log-linear sampling over ``wave_range`` (default = False)
        :param: **folder**: set to folder containing the Livingston and Wallace files (default = SPLAT's reference folder)
        :param: **output**: set to one of the following possible outputs:
            - ``transmission`` (default) - a numpy array containing the transmission spectrum
            - ``spectrum`` - a Spectrum object containing the transmission spectrum

    Output:

        Either a numpy array or Spectrum object containing the transmission spectrum sampled 
        over the wavelength range provided, with values ranging from 0 to 1

    Example:

    >>> import splat.model as spmdl
    >>> trans = spmdl.loadTelluric(wave_range=[1.3,1.5],ndata=1000)
    >>> print(trans)
        [  9.89881739e-01   9.77062180e-01   9.64035135e-01   1.00051461e+00
           9.96495927e-01   9.96135086e-01   9.97309832e-01   9.17222383e-01
           8.20866597e-01   9.24702335e-01   9.97319517e-01   9.97450808e-01
           8.98421113e-01   9.98372247e-01   9.60017183e-01   9.98449332e-01
           9.94087424e-01   9.52683627e-01   9.87684348e-01   7.75109019e-01
           9.76381023e-01   9.89867274e-01   8.71284143e-01   8.79453464e-01
           8.85513893e-01   9.96684751e-01   9.89084643e-01   9.80117987e-01
           9.85237657e-01   9.93525954e-01   9.95844421e-01   7.88396747e-01
           9.82524939e-01   9.98155509e-01   9.96245824e-01   9.55002105e-01   ... 
    >>> trans = spmdl.loadTelluric(wave_range=[1.3,1.5],ndata=1000,output='spectrum')
    >>> trans.info()
        Telluric transmission spectrum

        If you use these data, please cite Livingston, W. & Wallace, L. (1991, UNKNOWN, , )
        bibcode = 1991aass.book.....L
    '''

# prep inputs
    if len(args)>0: 
        wave = args[0]
        ndata = len(wave)
        wave_range = [numpy.min(wave),numpy.max(wave)]
    else:
        if (isinstance(wave_range,list) or isinstance(wave_range,numpy.ndarray)):
            if ndata==None:
                wave = wave_range
            else:
                if len(wave_range) >= 2:
                    if linear == True:
                        wave = numpy.linspace(wave_range[0],wave_range[1],ndata)
                    if log == True:
                        wave = numpy.logspace(wave_range[0],wave_range[1],ndata)
                else:
                    raise ValueError('\nCould not generate wavelength array with wave_range = {} and ndata = {}'.format(wave_range,ndata))
        else:
            raise ValueError('\nwave_range needs to be a list or numpy array')
    if isUnit(wave):
        wave = wave.to(DEFAULT_WAVE_UNIT)
        wave = wave.value
        wave_range = [numpy.min(wave),numpy.max(wave)]
    if not isinstance(wave,numpy.ndarray):
        wave = numpy.array(wave)
    if len(wave) < 2:
        raise ValueError('\nWavelength parameter {} should be a list of wavelengths'.format(wave))
    
# prep files
    tfiles = glob.glob(folder+'wn*')
    tfiles.reverse()
    tfiles = numpy.array(tfiles)
    tfwv = numpy.array([1.e4/float(f[len(folder+'wn'):]) for f in tfiles])
# select only those files in the range of wavelengths
#    tfiles = tfiles[
    w = numpy.where(numpy.logical_and(tfwv > numpy.min(wave),tfwv < numpy.max(wave)))
    tfiles_use = tfiles[w]
    if w[0][0] > 0: tfiles_use = numpy.append(tfiles_use,tfiles[w[0][0]-1])
    if w[0][0] < len(tfiles)-1: tfiles_use = numpy.append(tfiles_use,tfiles[w[0][-1]+1])

# generate raw wavelength and transmission list
    twave = []
    trans = []
    for f in tfiles_use:
        dp = pandas.read_csv(f,delimiter='\s+',names=['wavenum','flux','atm','total'])
        twave.extend([1.e4/w for w in dp['wavenum']])
        trans.extend([float(x) for x in dp['atm']])
    trans = numpy.array([x for (y,x) in sorted(zip(twave,trans))])
#    trans = numpy.array(trans)
    twave = numpy.array(sorted(twave))
#    plt.plot(twave,trans)
#    plt.xlim([2.292,2.33])

# resample onto desired wavelength scale via numerical integration
    if ndata == None:
        trans_sampled = trans[numpy.where(numpy.logical_and(twave >= numpy.min(wave_range),twave <= numpy.max(wave_range)))]
        wave = twave[numpy.where(numpy.logical_and(twave >= numpy.min(wave_range),twave <= numpy.max(wave_range)))]
# something bad is happening at this step
    else:
        wave = numpy.array(sorted(wave))
        trans_sampled = integralResample(twave,trans,wave)
    trans_sampled*=(u.m/u.m)

# return data
    if 'spec' in output.lower():
        mkwargs = {
        'wave': wave,
        'flux': trans_sampled,
        'noise': [numpy.nan for t in trans_sampled],
        'name': 'Telluric transmission',
        'funit': u.m/u.m,
        'wunit': DEFAULT_WAVE_UNIT,
        'bibcode': '1991aass.book.....L',
        'istransmission': True
        } 
        atm = Spectrum(**mkwargs)
        atm.funit = u.m/u.m
        return atm
    else: 
        return numpy.array(trans_sampled)



def blackbody(temperature,**kwargs):
    '''
    This program is still in development
    '''

    nsamp = kwargs.get('samples',1000)
    nsamp = kwargs.get('nsamp',nsamp)
    wunit = kwargs.get('wunit',DEFAULT_WAVE_UNIT)
    wunit = kwargs.get('wave_unit',wunit)
    w0 = kwargs.get('w0',0.1*DEFAULT_WAVE_UNIT)
    w0 = kwargs.get('lam0',w0)
    w1 = kwargs.get('w1',100.*DEFAULT_WAVE_UNIT)
    w1 = kwargs.get('lam1',w1)
    wrng = kwargs.get('wave_range',[w0,w1])
    wrng = kwargs.get('range',wrng)
    wrng = kwargs.get('wrng',wrng)
    if not isUnit(wrng[0]):
        wrng = [w*wunit for w in wrng]
    wrng = [w.to(wunit) for w in wrng]
    if not isUnit(temperature):
        temperature *= u.K
    logsamp = kwargs.get('log',False)
    logsamp = kwargs.get('logsample',logsamp)

    wave = numpy.linspace(wrng[0],wrng[1],nsamp)
    if logsamp == True: wave = numpy.logspace(numpy.log10(wrng[0].value),numpy.log10(wrng[1].value),nsamp)*wunit
    wave = kwargs.get('wave',wave)
    if not isUnit(wave):
        wave*=wunit

    flux = numpy.pi*((2.*const.h*const.c**2)/(wave**5)).to(DEFAULT_FLUX_UNIT)/(numpy.exp((const.h*const.c/(const.k_B*wave*temperature)).to(u.m/u.m))-1.)
    return splat.Spectrum(wave=wave,flux=flux,name='Blackbody T = {} K'.format(temperature.value),surface=True)


#######################################################
#######################################################
##################   MODEL FITTING  ###################
#######################################################
#######################################################



def _modelFitPlotComparison(spec,model,display=True,**kwargs):
    '''
    Routine to compare spectrum to a model or models
    '''

# set up model spectrum or spectra
    if isinstance(model,list) == False:
        model = [model]
    scale = kwargs.get('scale',[1.0]*len(model))
    if isinstance(scale,list) == False:
        scale = [scale]
    stat = kwargs.get('stat',[False]*len(model))
    if isinstance(stat,list) == False:
        stat = [stat]
    if kwargs.get('compare',False) == True:
        scale = []
        stat = []
        for i,m in enumerate(model):
            st,sc = compareSpectra(spec,m,stat='chisqr',**kwargs)      # note: assumed to be chi-square
            scale.append(sc)
            stat.append(st)
    for i,m in enumerate(model):
        m.scale(scale[i])

# plotting
    olegend = kwargs.get('name',spec.name)

# plot one model on top of one spectrum in one plot
    if kwargs.get('overplot',True) == True and len(model) == 1:
        sps = [spec,model[0]]
#        model[0].info()
        colors = ['k','b']
        mlegend = r'{} '.format(SPECTRAL_MODELS[getattr(model[0],'model')]['name'])
        mlegend+='{:s}={:.0f} '.format(SPECTRAL_MODEL_PARAMETERS['teff']['title'],getattr(model[0],'teff'))
        mlegend+='{:s}={:.2f} '.format(SPECTRAL_MODEL_PARAMETERS['logg']['title'],getattr(model[0],'logg'))
        mlegend+='{:s}={:.1f} '.format(SPECTRAL_MODEL_PARAMETERS['z']['title'],getattr(model[0],'z'))
        legend = [olegend,mlegend]
        if kwargs.get('showdifference',True) == True: 
            sps.append(spec-model[0])
            colors.append('grey')
            legend.append(r'Difference ($\chi^2$ = {:.0f})'.format(stat[i]))
        sps = tuple(sps)
        return splot.plotSpectrum(*sps,colors=kwargs.get('colors',colors),file=kwargs.get('file',False),\
            uncertainty=kwargs.get('uncertainty',True),telluric=kwargs.get('telluric',True),legend=legend)

# plot several models on top of spectrum in one plot
    elif kwargs.get('overplot',True) == True and len(model) > 1:
        sps = [spec]
        colors = ['k']
        legend = [olegend]
        for i,m in enumerate(model):
            sps.append(m)
            colors.append('grey')
            mlegend = r'{:s}={:.0f} '.format(SPECTRAL_MODEL_PARAMETERS['teff']['title'],getattr(m,'teff'))
            mlegend+='{:s}={:.2f} '.format(SPECTRAL_MODEL_PARAMETERS['logg']['title'],getattr(m,'logg'))
            mlegend+='{:s}={:.1f} '.format(SPECTRAL_MODEL_PARAMETERS['z']['title'],getattr(m,'z'))
            legend.append(mlegend)
        sps = tuple(sps)
        return splot.plotSpectrum(*sps,colors=kwargs.get('colors',colors),file=kwargs.get('file',False),\
            uncertainty=kwargs.get('uncertainty',True),telluric=kwargs.get('telluric',True),legend=legend)

# plot individual panels of spectra - there must be a filename given
    else: 
        if kwargs.get('file',False) == False:
            kwargs['file'] = 'modelFitComparison.pdf'
        plotlist = []
        legends = []
        colors = []
        for i,m in enumerate(model): 
            sps = [spec,m]
            c = ['k','b']
            mlegend = r'{}\n'.format(SPECTRAL_MODELS[getattr(m,'model')]['citation'])
            mlegend+='{:s}={:.0f} '.format(SPECTRAL_MODEL_PARAMETERS['teff']['title'],getattr(m,'teff'))
            mlegend+='{:s}={:.2f} '.format(SPECTRAL_MODEL_PARAMETERS['logg']['title'],getattr(m,'logg'))
            mlegend+='{:s}={:.1f} '.format(SPECTRAL_MODEL_PARAMETERS['z']['title'],getattr(m,'z'))
            leg = [olegend,mlegend]
            if kwargs.get('showdifference',True): 
                plotlist.append(spec-m)
                c.append('grey')
                leg.append(r'Difference ($\chi^2$ = {:.0f})'.format(stat[i]))
            plotlist.append(sps)
            colors.append(kwargs.get('colors',c))
            legends.append(leg)

        return splot.plotSpectrum(plotlist,multiplot=True,multipage=True,legends=legends,colors=colors,\
            file=kwargs.get('file',False),uncertainty=kwargs.get('uncertainty',True),telluric=kwargs.get('telluric',True))




def modelFitGrid(specin, modelset='btsettl08', instrument='', nbest=1, plot=True, statistic='chisqr', verbose=False, output='fit', radius=0.1*u.Rsun, radius_tolerance=0.01*u.Rsun, radius_model='', constrain_radius=False, **kwargs):
    '''
    :Purpose: 

        Fits a spectrum to a grid of atmosphere models, reports the best-fit and weighted average parameters, 
        and returns either a dictionary with the best-fit model parameters or the model itself scaled to the optimal scaling factor.
        If spectrum is absolutely flux calibrated with the `fluxcalibrate()`_ method, the routine will also calculate 
        the equivalent radii of the source. In addition, an input radius can be used to provide an additional constraint on the model

    Required inputs:

    :param spec: a Spectrum class object, which should contain wave, flux and noise array elements.

    Optional inputs:

    :param model: set of models to use (``set`` and ``model_set`` may also be used), from the available models given by `loadModel()`_.


    :param stat: the statistic to use for comparing models to spectrum; can be any one of the statistics allowed in `compareSpectra()`_ routine (default = `chisqr`)


    :param nbest: sets the number of best-fit models to return (default = 1)

    :param weights: an array of the same length as the spectrum flux array, specifying the weight for each pixel (default: equal weighting)
    :param mask: an array of the same length as the spectrum flux array, specifying which data to include in comparison statistic as coded by 0 = good data, 1 = bad (masked). The routine `generateMask()`_ is called to create a mask, so parameters from that routine may be specified (default: no masking)


    :param compute\_radius: if set to True, force the computation of the radius based on the model scaling factor. This is automatically set to True if the input spectrum is absolutely flux calibrated (default = False)

    :param teff\_range: set to the range of temperatures over which model fitting will be done (``temperature_range`` and ``t_range`` may also be used; default = full range of model temperatures)
    :param logg\_range: set to the range of surface gravities over which model fitting will be done (``gravity_range`` and ``g_range`` may also be used; default = full range of model temperatures)
    :param z\_range: set to the range of metallicities over which model fitting will be done (``metallicity_range`` may also be used; default = full range of model temperatures)

    :param return\_model: set to True to return a Spectrum class of the best-fit model instead of a dictionary of parameters (default = False)
    :param return\_mean\_parameters: set to True a dictionary of mean parameters (default = False)
    :param return\_all\_parameters: set to True to return all of the parameter sets and fitting values (default = False)

    :param summary: set to True to report a summary of results (default = True)
    :param output: a string containing the base filename for outputs associated with this fitting routine (``file`` and ``filename`` may also be used; default = 'fit')
    :param plot: set to True to suppress plotting outputs (default = False)
    :param plot\_format: specifes the file format for output plots (default = `pdf`)
    :param file\_best\_comparison: filename to use for plotting spectrum vs. best-fit model (default = '``OUTPUT``\_best\_comparison.``PLOT_FORMAT``')
    :param file\_mean\_comparison: filename to use for plotting spectrum vs. mean parameter model (default = '``OUTPUT``\_mean\_comparison.``PLOT_FORMAT``')

    In addition, the parameters for `compareSpectra()`_ , `generateMask()`_ and `plotSpectrum()`_ may be used; see SPLAT API for details.

    Output:
    
    Default output is a dictionary containing the best-fit model parameters: model name, teff, logg, z, fsed, kzz, cloud and slit, as well as the scaling factor for the model and comparison statistic.  
    If the input spectrum is absolutely flux calibrated, radius is also returned.  Alternate outputs include:

        *  a dictionary of the statistic-weighted mean parameters (``return_mean_parameters`` = True)
        *  a list of dictionaries containing all parameters and fit statistics (``return_all_parameters`` = True)
        *  a Spectrum class of the best-fit model scaled to the best-fit scaling (``return_model`` = True)

    :Example:
    >>> import splat
    >>> import splat.model as spmod
    >>> sp = splat.getSpectrum(shortname='1507-1627')[0]
    >>> sp.fluxCalibrate('2MASS J',12.32,absolute=True)
    >>> p = spmod.modelFitGrid(sp,teff_range=[1200,2500],model='Saumon',file='fit1507')
        Best Parameters to fit to BT-Settl (2008) models:
            $T_{eff}$=1800.0 K
            $log\ g$=5.0 dex(cm / s2)
            $[M/H]$=-0.0 dex
            $f_{sed}$=nc 
            $cld$=nc 
            $log\ \kappa_{zz}$=eq dex(cm2 / s)
            R=0.143324498969 solRad
            chi=4500.24997585
        Mean Parameters:
            $T_{eff}$: 1800.0+/-0.0 K
            $log\ g$: 5.0+/-0.0 dex(cm / s2)
            Radius: 0.143324498969+/-0.0 solRad
            $[M/H]$: 0.0+/-0.0 dex

    .. _`fluxcalibrate()` : api.html#splat.Spectrum.fluxCalibrate
    .. _`generateMask()` : api.html#splat.generateMask
    .. _`loadModel()` : api.html#splat_model.loadModel
    .. _`plotSpectrum()`: api.html#splat_plot.plotSpectrum
    .. _`compareSpectra()` : api.html#splat.compareSpectra
    '''
# fitting parameters
    statistic = kwargs.get('stat',statistic)
#    mask = kwargs.get('mask',generateMask(spec.wave,**kwargs))
#    fit_range = kwargs.get(fit_range,[numpy.nanmin(spec.wave),numpy.nanmax(spec.wave)])
#    weights = kwargs.get('weights',numpy.ones(len(spec.wave)))

# check model name
    modelset = kwargs.get('model', modelset)
    modelset = kwargs.get('set', modelset)
    modelset = kwargs.get('model_set', modelset)
    mset = checkSpectralModelName(modelset)
    if mset == False:
        raise ValueError('\n{} is not in the SPLAT model suite; try {}'.format(modelset,' '.join(list(SPECTRAL_MODELS.keys()))))
    if verbose == True:
        print('\nmodelFitGrid is using {} model set'.format(mset))
        kwargs['summary'] = True

# instrument parameters - identify from data or input
    instrument = kwargs.get('instr',instrument)
    try:
        if instrument == '': instrument = specin.instrument
    except:
        pass
    instr = checkInstrument(instrument)
    if instr == False: instr=instrument
    if verbose == True: print('modelFitGrid is using {} instrument'.format(instr))

# make sure instrument computed for model set
    if instr not in list(SPECTRAL_MODELS[mset]['instruments']):
        raise ValueError('{} models for instrument {} have not been computed; run processModelsToInstrument()'.format(mset,instr))

# constrain model radius? if so, make sure evolutionary model is correct
    if constrain_radius==True:
        evol_flag = False
        if radius_model != '':
            mrad = spev.checkEvolutionaryModelName(radius_model)
            if mrad != False:
                radius_model = mrad
                evol_flag = True
    if not isUnit(radius): radius=radius*u.Rsun
    radius = radius.to(u.Rsun)
    if not isUnit(radius_tolerance): radius_tolerance=radius_tolerance*u.Rsun
    radius_tolerance = radius_tolerance.to(u.Rsun)

# copy of spectrum
    spec = copy.deepcopy(specin)

# plotting and reporting keywords
    compute_radius = kwargs.get('compute_radius', spec.fscale == 'Absolute')
    output = kwargs.get('filename',output)
    output = kwargs.get('file',output)
    plot_format = kwargs.get('plot_format','pdf')
    file_best_comparison = kwargs.get('file_best_comparison',os.path.splitext(output)[0]+'_best_comparison.'+plot_format)
#    file_mean_comparison = kwargs.get('file_mean_comparison',os.path.splitext(output)[0]+'_mean_comparison.'+plot_format)
#    file_corner = kwargs.get('file_corner',os.path.splitext(output)[0]+'_corner.'+plot_format)

#    file_iterative = kwargs.get('file_iterative',os.path.splitext(filebase)[0]+'_iterative.dat')
#    file_chains = kwargs.get('file_chains',os.path.splitext(filebase)[0]+'_chains.'+plot_format)
#    file_corner = kwargs.get('file_corner',os.path.splitext(filebase)[0]+'_corner.'+plot_format)
#    file_summary = kwargs.get('file_summary',os.path.splitext(filebase)[0]+'_summary.txt')
#    if kwargs.get('save',True):
#        f = open(file_iterative,'w')
#        f.close()

# read in available model grid points
    gridparam = _loadModelParameters(mset,instr) 

# populate ranges
    ranges = {}
    for ms in list(SPECTRAL_MODEL_PARAMETERS.keys()):
        if ms in list(gridparam.keys()):
            if SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'continuous':
                rng = kwargs.get('{}_range'.format(ms),[numpy.min(gridparam[ms]),numpy.max(gridparam[ms])])
            else:
                rng = numpy.unique(gridparam[ms])
            rng = kwargs.get('{}_range'.format(SPECTRAL_MODEL_PARAMETERS[ms]['name']),rng)
            rng = kwargs.get('{}_range'.format(SPECTRAL_MODEL_PARAMETERS[ms]['prefix']),rng)
            ranges[ms] = rng
            if ms == 'z' and kwargs.get('nometallicity',False) == True: ranges[ms] = [0,0]


# select models to fit by checking ranges
    parameters = []
    for p in gridparam['parameter_sets']:
        test = True
        for ms in list(SPECTRAL_MODEL_PARAMETERS.keys()):
            if ms in list(p.keys()):
                if SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'continuous':
                    if float(p[ms]) < numpy.nanmin(ranges[ms]) or float(p[ms]) > numpy.nanmax(ranges[ms]): test = (test and False)
                else:
                    if p[ms] not in ranges[ms]: test = (test and False)
        if test == True: parameters.append(p)
    parameters = numpy.array(parameters)
# test away    
#    stats = []
    for p in parameters:
        model = loadModel(**p,force=True)
        mkwargs = copy.deepcopy(kwargs)
        mkwargs['plot'] = False
        chi,scl = compareSpectra(spec, model, stat=statistic, **mkwargs)
        p['stat'] = chi
        p['scale'] = scl
        p['radius'] = ((scl*(10.*u.pc)**2)**0.5).to(u.Rsun)
        print(p['radius'],scl)

# use radius as a constraint
        if constrain_radius == True:
            if evol_flag == True:
                epar = spev.modelParameters(temperature=p['teff'],gravity=p['logg'],model=radius_model)
                if numpy.isnan(epar['radius']): 
                    chi = chi*10.  # penalty for being outside evolutionary model range
                else:
                    radius = epar['radius']
                    if not isUnit(radius): radius = radius*u.Rsun
                    radius.to(u.Rsun)
                    scl = scl*((radius/p['radius']).value)**2
                    model.scale(scl)
                    chi,scl = compareSpectra(spec, model, stat=statistic, scale=False, **mkwargs)
            else: 
                print(scl,radius,p['radius'])
                scl = scl*((radius/p['radius']).value)**2
                print(scl)
                model.scale(1./scl)
                chi,scl = compareSpectra(spec, model, stat=statistic, scale=False, **mkwargs)
            p['stat'] = chi
            p['scale'] = scl
            p['radius'] = ((scl*(10.*u.pc)**2)**0.5).to(u.Rsun)


#        if verbose == True: print(p)


# report best parameters
    stats = numpy.array([(p['stat']*u.m/u.m).value for p in parameters])
#    parameters = [x for (y,x) in sorted(zip(stats,parameters))]
    parameters = parameters[numpy.argsort(stats)]
    stats = numpy.sort(stats)
#    print('\n\n')
#    for i,s in enumerate(stats):
#        line = '{}: chi={}'.format(i,s)
#        for ms in MODEL_PARAMETER_NAMES[:-1]:
#            line+='{} = {} {}'.format(MODEL_PARAMETER_TITLES[ms],parameters[i][ms],MODEL_PARAMETER_UNITS[ms])
#        if compute_radius == True:
#            line+='Radius = {} {}'.format(parameters[i]['radius'].value,parameters[i]['radius'].unit)
#        print(line)
    bparam = copy.deepcopy(parameters[0])
    bmodel = copy.deepcopy(loadModel(**bparam))
    bmodel.scale(parameters[0]['scale'])

    if verbose == True: 
        print('\nBest Parameters to fit to {} models:'.format(SPECTRAL_MODELS[mset]['name']))
        for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
            if ms in list(parameters[0].keys()):
                print('\t{} = {} {}'.format(SPECTRAL_MODEL_PARAMETERS[ms]['title'],parameters[0][ms],SPECTRAL_MODEL_PARAMETERS[ms]['unit']))
        if compute_radius == True:
            print('\tRadius = {} {}'.format(parameters[0]['radius'].value,parameters[0]['radius'].unit))
        print('\tchi={}'.format(parameters[0]['stat']))

    if plot == True:
        best_plot = _modelFitPlotComparison(spec,bmodel,stat=stats[0],file=file_best_comparison)

# weighted means/uncertainties - REMOVED THIS
#     fitweights = numpy.exp(-0.5*(numpy.array(stats)-numpy.nanmin(stats))/len(spec.wave))
#     fparam = copy.deepcopy(parameters[0])
#     for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
#         if ms in list(parameters[0].keys()) and SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'continuous':
#             vals = [(p[ms]*(u.m/u.m)).value for p in parameters]
#             fparam[ms],fparam[ms+'_unc'] = weightedMeanVar(vals,fitweights)
#             fparam[ms]*=SPECTRAL_MODEL_PARAMETERS[ms]['unit']
#             fparam[ms+'_unc']*=SPECTRAL_MODEL_PARAMETERS[ms]['unit']
#     if compute_radius == True:
#         vals = [(p['radius']*(u.m/u.m)).value for p in parameters]
#         fparam['radius'],fparam['radius_unc'] = weightedMeanVar(vals,fitweights)
#         fparam['radius']*=u.Rsun
#         fparam['radius_unc']*=u.Rsun

#     if kwargs.get('summary',True) == True:
#         print('\nStatistic-weighted Mean Parameters:')
#         for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
#             if ms in list(fparam.keys()) and SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'continuous':
#                 print('\t{}: {}+/-{} {}'.format(SPECTRAL_MODEL_PARAMETERS[ms]['title'],fparam[ms].value,fparam[ms+'_unc'].value,fparam[ms].unit))
#         if compute_radius == True:
#             print('\tRadius = {}+/-{} {}'.format(fparam['radius'].value,fparam['radius_unc'].value,fparam['radius'].unit))
# #        if k == 'radius':
# #            print('\tRadius: {}+/-{} {}'.format(fparam[k].value,fparam[k+'_unc'].value,fparam[k].unit))

    # if plot == True:
    #     try:
    #         mmodel = loadModel(**fparam)
    #     except:
    #         print('\nWarning! Could not load model {} for parameters {}'.format(mset,fparam))
    #     else:
    #         chi,scl = compareSpectra(spec, mmodel, stat=stat, **kwargs)
    #         mmodel.scale(scl)
    #         _modelFitPlotComparison(spec,mmodel,stat=chi,file=file_mean_comparison)


# generate corner plot for Teff, logg, z
# this needs to be done more like a heat map of chisquare
#    if kwargs.get('plot',True) == True:
        # try:
        #     import corner
        # except:
        #     print('\nWarning! Must install corner to make a corner plot: https://github.com/dfm/corner.py')
        # else:
        #     pvar = []
        #     for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
        #         if splat.SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'continuous' and ms in list(parameters[0].keys()): pvar.append(ms)
        #     if compute_radius == True: pvar.append('radius')
        #     plotp = {}
        #     for ms in pvar: plotp[ms] = []
        #     for p in parameters:
        #         for ms in pvar:
        #             plotp[ms].append((p[ms]*(u.m/u.m)).value)
        #     pd = pandas.DataFrame(plotp)
        #     pd = pd[pvar]
        #     prange = []
        #     for ms in pvar:
        #         if ms == 'radius':
        #             d = 0.
        #         else:
        #             d = numpy.nanmax(pd[ms])-numpy.nanmin(pd[ms])
        #             d = numpy.nanmax([d,0.05*(numpy.nanmax(gridparam[ms])-numpy.nanmin(gridparam[ms]))])
        #         prange.append((numpy.nanmin(pd[ms])-d,numpy.nanmax(pd[ms])+d))
        #     fig = corner.corner(pd,weights=fitweights,labels=[SPECTRAL_MODEL_PARAMETERS[ms]['title'] for ms in pvar],range=prange,truths=[(fparam[ms]*u.m/u.m).value for ms in pvar],show_titles=True)
        #     fig.savefig(file_corner)



# return parameters; otherwise return 
    if kwargs.get('return_model',False) == True:
        return bmodel
    elif kwargs.get('return_mean_parameters',False) == True:
        return fparam
    elif kwargs.get('return_all_parameters',False) == True:
        return parameters
    else:
        if nbest == 1:
            return parameters[0]
        else:
            return parameters[:nbest]



def modelFitMCMC(specin, modelset='BTSettl2008', instrument='SPEX-PRISM', verbose=False, nsamples=1000, burn=0.1, **kwargs):
    '''
    :Purpose: Uses Metropolis-Hastings Markov Chain Monte Carlo method to compare a spectrum to
                atmosphere models. Returns the best estimate of whatever parameters are allowed to
                vary; can also compute the radius based on the scaling factor.
    :param spec: Spectrum class object, which should contain wave, flux and noise array elements (required)
    :param nsamples: number of MCMC samples (optional, default = 1000)
    :param burn: the decimal fraction (0 to 1) of the initial steps to be discarded (optional; default = 0.1; alternate keywords ``initial_cut``)
    :param set: set of models to use; see loadModel for list (optional; default = 'BTSettl2008'; alternate keywords ``model``, ``models``)
    :param verbose: give lots of feedback (optional; default = False)
    :param showRadius: set to True so evaluate radius (optional; default = False unless spec is absolute flux calibrated)

    Also takes commands for compareSpectra

    
    :param output: filename or filename base for output files (optional; alternate keywords ``filename``, ``filebase``)
    :param savestep: indicate when to save data output; e.g. ``savestep = 10`` will save the output every 10 samples (optional, default = ``nsamples``/10)



    :param dataformat: output data format type
    :type dataformat: optional, default = 'ascii.csv'
    :param initial_guess: array including initial guess of the effective temperature, surface gravity and metallicity of ``spec``.
                            Can also set individual guesses of spectral parameters by using **initial_temperature** or **initial_teff**,
                            **initial_gravity** or **initial_logg**, and **initial_metallicity** or **initial_z**.
    :type initial_guess: optional, default = array of random numbers within allowed ranges
    :param ranges: array of arrays indicating ranges of the effective temperature, surface gravity and metallicity of the model set.
                    Can also set individual ranges of spectral parameters by using **temperature_range** or **teff_range**,
                    **gravity_range** or **logg_range**, and **metallicity_range** or **z_range**.
    :type ranges: optional, default = depends on model set
    :param step_sizes: an array specifying step sizes of spectral parameters. Can also set individual step sizes by using
                        **temperature_step** or **teff_step**, **gravity_step** or **logg_step**, and **metallicity_step** or **z_step**.
    :type step_sizes: optional, default = [50, 0.25, 0.1]
    :param nonmetallicity: if True, sets metallicity = 0
    :type nonmetallicity: optional, default = False
    :param addon: reads in prior calculation and starts from there. Allowed object types are tables, dictionaries and strings.
    :type addon: optional, default = False
    :param evolutionary_model: set of evolutionary models to use. See Brown Dwarf Evolutionary Models page for
        more details. Options include:
    
        - *'baraffe'*: Evolutionary models from `Baraffe et al. (2003) <http://arxiv.org/abs/astro-ph/0302293>`_.
        - *'burrows'*: Evolutionary models from `Burrows et al. (1997) <http://adsabs.harvard.edu/abs/1997ApJ...491..856B>`_.
        - *'saumon'*: Evolutionary models from `Saumon & Marley (2008) <http://adsabs.harvard.edu/abs/2008ApJ...689.1327S>`_.
        
    :type evolutionary_model: optional, default = 'Baraffe'
    :param emodel: the same as ``evolutionary_model``
    :type emodel: optional, default = 'Baraffe'
    
    :Example:
    >>> import splat
    >>> import splat.model as spmod
    >>> sp = splat.getSpectrum(shortname='1047+2124')[0]        # T6.5 radio emitter
    >>> parameters = spmod.modelFitMCMC(sp,initial_guess=[900,5.0,0.0],nsamples=1000)
    '''

# MCMC keywords
    timestart = time.time()
    burn = kwargs.get('initial_cut', burn)  # what fraction of the initial steps are to be discarded
    if burn > 1.: burn = burn/nsamples

# check model name
    modelset = kwargs.get('model', modelset)
    modelset = kwargs.get('set', modelset)
    modelset = kwargs.get('model_set', modelset)
    mset = checkSpectralModelName(modelset)
    if mset == False:
        raise ValueError('\n{} is not in the SPLAT model suite; try {}'.format(modelset,' '.join(list(SPECTRAL_MODELS.keys()))))
    if verbose == True:
        print('\nmodelFitMCMC is using {} model set'.format(mset))
        kwargs['summary'] = True

# instrument parameters - identify from data or input
    instrument = kwargs.get('instr',instrument)
    try:
        if instrument == '': instrument = specin.instrument
    except:
        pass
    instr = checkInstrument(instrument)
    if instr == False: instr=instrument
    if verbose == True: print('modelFitMCMC is using {} instrument'.format(instr))

# make sure instrument computed for model set
    if instr not in list(SPECTRAL_MODELS[mset]['instruments']):
        raise ValueError('{} models for instrument {} have not been computed; run processModelsToInstrument()'.format(mset,instr))

# copy of spectrum
    spec = copy.deepcopy(specin)


# plotting and reporting keywords
    showRadius = kwargs.get('showRadius', spec.fscale == 'Absolute')
    showRadius = kwargs.get('radius', showRadius)
    try:
        filebase = kwargs.get('filebase', 'fit_'+spec.name+'_'+mset)
    except:
        filebase = kwargs.get('filebase', 'fit_'+mset)
    filebase = kwargs.get('filename', 'fit_'+mset)
    filebase = kwargs.get('folder', '')+filebase
#    kwargs['filebase'] = filebase
    output_parameters = kwargs.get('output_parameters',filebase+'modelfitmcmc_parameters.csv')
    output_chain = kwargs.get('output_chain',filebase+'modelfitmcmc_chain.pdf')
    output_corner = kwargs.get('output_corner',filebase+'modelfitmcmc_corner.pdf')
    output_comparison = kwargs.get('output_comparison',filebase+'modelfitmcmc_bestfit.pdf')
    output_summary = kwargs.get('output_summary',filebase+'modelfitmcmc_summary.txt')
    try:
        srcname = kwargs.get('name',spec.name)
    except:
        srcname = kwargs.get('name','Source')
    savestep = kwargs.get('savestep', nsample/10)    
#    dataformat = kwargs.get('dataformat','ascii.csv')
# evolutionary models    
    emodel = kwargs.get('evolutionary_model', 'baraffe03')
    emodel = kwargs.get('evolution', emodel)
    emodel = kwargs.get('emodel', emodel)

# set mask   
    mask_ranges = kwargs.get('mask_ranges',None)
    mask = kwargs.get('mask',generateMask(spec.wave,**kwargs))
    
# set the degrees of freedom    
    try:
        slitwidth = spec.slitpixelwidth
    except:
        slitwidth = 3.
    eff_dof = numpy.round((numpy.nansum(1.-numpy.array(mask)) / slitwidth) - 1.)

# set ranges for models - input or set by model itself
    param_range = {}
    modelgrid = _loadModelParameters(mset,instrument) # Range parameters can fall in
    for ms in list(SPECTRAL_MODELS[mset]['default'].keys()): 
        if SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'continuous':
            param_range[ms] = [numpy.min(modelgrid[ms]),numpy.max(modelgrid[ms])]
        else:
            param_range[ms] = modelgrid[ms]
    param_range['teff'] = kwargs.get('teff_range',param_range['teff'])
    param_range['teff'] = kwargs.get('temperature_range',param_range['teff'])
    param_range['logg'] = kwargs.get('logg_range',param_range['logg'])
    param_range['logg'] = kwargs.get('gravity_range',param_range['logg'])
    param_range['z'] = kwargs.get('z_range',param_range['z'])
    param_range['z'] = kwargs.get('metallicity_range',param_range['z'])

# set initial parameters
    param0 = {}
    for ms in list(param_range.keys()): param0[ms] = SPECTRAL_MODELS[mset]['default'][ms]
    p = kwargs.get('initial_guess',[param0['teff'],param0['logg'],param0['z']])
    if len(p) < 3: p.append(0.)
    param0['teff'] = kwargs.get('initial_temperature',p[0])
    param0['teff'] = kwargs.get('initial_teff',param0['teff'])
    param0['logg'] = kwargs.get('initial_gravity',p[1])
    param0['logg'] = kwargs.get('initial_logg',param0['logg'])
    param0['z'] = kwargs.get('initial_metallicity',p[2])
    param0['z'] = kwargs.get('initial_z',param0['z'])
#    kwargs.get('initial_guess',[\
#        numpy.random.uniform(teff_range[0],teff_range[1]),\
#        numpy.random.uniform(logg_range[0],logg_range[1]),\
#        numpy.random.uniform(z_range[0],z_range[1])])
#        numpy.random.uniform(0.,0.)])
#    if len(param0_init) < 3:
#        param0_init.append(0.0)
        
# set parameter steps for continuous variables
    param_step = {}
    for ms in list(param0.keys()): param_step[ms] = 0.
    p = kwargs.get('step_sizes',[50,0.1,0.1])
    param_step['teff'] = kwargs.get('teff_step',p[0])
    param_step['teff'] = kwargs.get('temperature_step',param_step['teff'])
    param_step['logg'] = kwargs.get('logg_step',p[1])
    param_step['logg'] = kwargs.get('gravity_step',param_step['logg'])
    param_step['z'] = kwargs.get('z_step',p[2])
    param_step['z'] = kwargs.get('metallicity_step',param_step['z'])
    if kwargs.get('nometallicity',False) == False or kwargs.get('vary_metallicity',True) == True:
        param_range['z'] = [0.,0.]
        param_step['z'] = 0.
        param0['z'] = 0.0
    if kwargs.get('vary_fsed',False) == True: param_step['fsed'] = 1.
    if kwargs.get('vary_cloud',False) == True: param_step['cld'] = 1.
    if kwargs.get('vary_kzz',False) == True: param_step['kzz'] = 1.

# choose what parameters to plot
    param_plot = []
    for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: 
        if param_step[ms] != 0.: param_plot.append(ms)
    if showRadius == True: param_plot.append('radius')

# read in prior calculation and start from there
    if kwargs.get('addon',False) != False:
        addflg = False
# a table is passed
        if isinstance(kwargs.get('addon'),Table):
            t = kwargs.get('addon')
            addflg = True
# a dictionary is passed
        elif isinstance(kwargs.get('addon'),dict):
            t = Table(kwargs.get('addon'))
            addflg = True
# a filename is passed
        elif isinstance(kwargs.get('addon'),str):
            try:
                p = ascii.read(os.path.normpath(kwargs.get('addon')))
            except:
                print('\nCould not read in parameter file {}'.format(kwargs.get('addon')))

# Check that initial guess is within range of models
    try:
        model = loadModel(set=mset, instrument=instrument, **param0)
    except:
        line=''
        for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: line+='{}:{} '.format(ms,param0[ms])
        raise ValueError('\nInitial parameter set {} outside of parameter range for {} models'.format(line,mset))
#    if not (numpy.min(param_range['teff']) <= param0['teff'] <= numpy.max(param_range['teff']) and \
#        numpy.min(param_range['teff']) <= param0['teff'] <= numpy.max(param_range['teff']) and \
#        numpy.min(param_range['teff']) <= param0['teff'] <= numpy.max(param_range['teff'])):
#        sys.stderr.write("\nInitial guess T={}, logg = {} and [M/H] = {} is out of model range;" + \
#            "defaulting to a random initial guess in range.".format(param0[0],param0[1],param0[2]))
#        param0 = param0_init
#        if param0[2] == 0.:
#            param_step[2] = 0.

    mkwargs = copy.deepcopy(kwargs)
    mkwargs['plot'] = False
    chisqr0,alpha0 = compareSpectra(spec, model, **mkwargs)
    chisqrs = [chisqr0]    
    params = [param0]
    radii = [(10.*u.pc*numpy.sqrt(alpha0)).to(u.Rsun)]
    for i in numpy.arange(nsample):
        for ms in SPECTRAL_MODEL_PARAMETERS_INORDER:
            param1 = copy.deepcopy(param0)
            if SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'continuous' and param_step[ms] != 0.:
                param1[ms] = numpy.random.normal(param1[ms],param_step[ms])
                vflag = True
            elif SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'discrete' and param_step[ms] != 0.:
                param1[ms] = numpy.random.choice(modelgrid[ms])
                vflag = True
                param_range[ms] = modelgrid[ms]
            else:
                vflag = False
#            print(ms, param_step[ms], param0[ms], param1[ms],vflag)
            if vflag:
                try:            
                    model = loadModel(set = mset, instrument=instrument,**param1)
                    mkwargs = copy.deepcopy(kwargs)
                    mkwargs['plot'] = False
                    chisqr1,alpha1 = compareSpectra(spec, model ,**mkwargs)  

# Probability that it will jump to this new point; determines if step will be taken
                    if kwargs.get('stat','ftest').lower() == 'ftest' or kwargs.get('stat','f-test').lower() == 'f-test':
                        h = 1. - stats.f.cdf(chisqr1/chisqr0, eff_dof, eff_dof)
                    elif kwargs.get('stat','ftest').lower() == 'exponential':
                        h = 1. - numpy.exp(0.5*(chisqr1-chisqr0)/eff_dof)
#                    print(chisqr1, chisqr0, eff_dof, h)
                    if numpy.random.uniform(0,1) < h:
                        param0 = copy.deepcopy(param1)
                        chisqr0 = copy.deepcopy(chisqr1)
                        alpha0 = copy.deepcopy(alpha1)
                
# update list of parameters, chi^2 and radii
                    params.append(param0)
                    chisqrs.append(chisqr0)
                    radii.append((10.*u.pc*numpy.sqrt(alpha0)).to(u.Rsun))
                    
                except:
                    if verbose:
                        line=''
                        for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: line+='{}:{} '.format(ms,param1[ms])
                        print('Trouble with model {} with parameters {}'.format(mset,line))
                    continue

        if verbose:
            line=''
            for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: line+='{}:{} '.format(ms,param0[ms])
            print('At cycle {}: chi2 = {:.1f} parameters {}'.format(i,chisqr0,line))


# save results iteratively
        if i*savestep != 0 and i%savestep == 0:
            dp = pandas.DataFrame(params)
            dp['radius'] = radii
            dp['chisqr'] = chisqrs
            dp['weights'] = [1.-stats.f.cdf(c/numpy.nanmin(chisqrs), eff_dof, eff_dof) for c in chisqrs]
            dp.to_csv(output_parameters,index=False)
            _modelFitMCMC_plotChains(dp,columns=param_plot,burn=burn,output=output_chain,stat='weights')
            _modelFitMCMC_plotCorner(dp[int(burn*len(dp)):],columns=param_plot,output=output_corner)
            param_best = {}
            for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: param_best[ms] = dp[ms].iloc[numpy.argmin(dp['chisqr'])]
            model = loadModel(set = mset, instrument=instrument,**param_best)
            line=''
            for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: 
                if param_step[ms] != 0.: line+='{}={:.2f} '.format(ms,param_best[ms])
            c,a = compareSpectra(spec, model, output=output_comparison,legend=[srcname,'{}\n{}'.format(SPECTRAL_MODELS[mset]['name'],line),'Difference'],**kwargs)
#            _modelFitMCMC_reportResults(spec,dp,iterative=True,model_set=mset,**kwargs)

# Final results
    dp = pandas.DataFrame(params)
    dp['radius'] = radii
    dp['chisqr'] = chisqrs
    dp['weights'] = [1.-stats.f.cdf(c/numpy.nanmin(chisqrs), eff_dof, eff_dof) for c in chisqrs]
    dp.to_csv(output_parameters,index=False)
    fig_chains = _modelFitMCMC_plotChains(dp,columns=param_plot,burn=burn,output=output_chain,stat='weights')
    fig_corner = _modelFitMCMC_plotCorner(dp[int(burn*len(dp)):],columns=param_plot,output=output_corner)
    param_best = {}
    for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: param_best[ms] = dp[ms].iloc[numpy.argmin(dp['chisqr'])]
    model = loadModel(set = mset, instrument=instrument,**param_best)
    line=''
    for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: 
        if param_step[ms] != 0.: line+='{}={:.2f} '.format(ms,param_best[ms])
    c,a = compareSpectra(spec, model, output=output_comparison,legend=[srcname,'{}\n{}'.format(SPECTRAL_MODELS[mset]['name'],line),'Difference'], **kwargs)

# save data    
    if verbose:
        print('\nTotal time elapsed = {}'.format(time.time()-timestart))
    if kwargs.get('return_model',False) == True: 
        return model.scale(a)
    if kwargs.get('return_chains',False) == True: 
        return fig_chains
    if kwargs.get('return_corner',False) == True: 
        return fig_corner
    else: return dp



def _modelFitMCMC_plotChains(dp,**kwargs):
    '''
    :Purpose: Plots the parameter chains from an MCMC analysis (internal program)
    :param database: pandas DataFrame or list of DataFrames providing the parameters used to plot (required)
    :param columns: list of strings specifying which columns to plot (optional; default is all columns)
    :param stat: special column that displays the fitting statistc
    :param burn: decimal fraction (0 to 1) of starting parameters to reject (optional; default = 0.)
    :param output: name of file for plotting chains (optional; alterate keywords file and filename)
    :param figsize: size of resulting figure (optional; default is set by number of parameters plotted)
    
    :Example:
    >>> import splat
    >>> import splat.model as spmod
    >>> sp = splat.getSpectrum(shortname='0415-0935')[0]
    >>> parameters = spmod.modelFitMCMC(sp,initial_guess=[800,5.0,0.0],nsamples=1000)
    >>> spmod._modelFitMCMC_plotChains(parameters,columns=['teff','logg','z'])
    '''

    plotname_assoc = {}
    for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: plotname_assoc[ms] = '{} ({})'.format(SPECTRAL_MODEL_PARAMETERS[ms]['title'],SPECTRAL_MODEL_PARAMETERS[ms]['unit'])
    plotname_assoc['mass'] = r'Mass (M$_{\odot}$)'
    plotname_assoc['age'] = r'Age (Gyr)'
    plotname_assoc['luminosity'] = r'log L$_{bol}$/L$_{\odot}$'
    plotname_assoc['radius'] = r'Radius (R$_{\odot}$)'
    plotname_assoc['denisty'] = r'$\rho$ ($\rho_{\odot}$)'
    stat = kwargs.get('stat', 'chisqr')

# check input format
    inp = copy.deepcopy(dp)
    if isinstance(inp,pandas.core.frame.DataFrame):
        inp = [inp]
    if isinstance(inp,list):
        if isinstance(inp[0],dict):
            try:
                tmp = [pandas.DataFrame(x) for x in inp]
                inp = tmp
            except:
                raise ValueError('\nInput must be a single or list of pandas dataframe or list of parameter dictionaries')
    else:
        print(type(inp),type(inp[0]))
        raise ValueError('\nCould not process input')

# prep output
    output = kwargs.get('output','')
    output = kwargs.get('file',output)
    output = kwargs.get('filename',output)
    columns = kwargs.get('columns',list(inp[0].columns))
    nplots = len(columns)
    if stat in list(dp.columns):
        nplots += 1

# make figure
    plt.clf()
    fig = plt.figure(1,figsize=kwargs.get('figsize',[8,4*(nplots)]))
    xr = [0,len(inp[0])-1]
    for i,ms in enumerate(columns):
        v = []
        for dp in inp: v.extend(list(dp[ms].values))
        if isUnit(v[0]):
            v = [x.value for x in v]
        plt.subplot(int('{}1{}'.format(nplots,i+1)))
        yr = [numpy.min(v),numpy.max(v)]
        yr[0] -= 0.05*(yr[1]-yr[0])
        yr[1] += 0.05*(yr[1]-yr[0])
#        print(yr)
        for dp in inp:
            plt.plot(numpy.arange(len(dp)),v,'k-',alpha=0.5)
        plt.xlim(xr)
        plt.ylim(yr)
        if kwargs.get('burn',0) > 0:
            plt.plot([kwargs['burn']*len(inp[0])]*2,yr,'k:')
            v = []
            for dp in inp: v.extend(list(dp[ms][int(kwargs['burn']*len(dp)):].values))
            if isUnit(v[0]):
                v = [x.value for x in v]
        plt.plot(xr,[numpy.nanmean(v),numpy.nanmean(v)],'r-')
        plt.plot(xr,[numpy.nanmean(v)+numpy.nanstd(v),numpy.nanmean(v)+numpy.nanstd(v)],'r:')
        plt.plot(xr,[numpy.nanmean(v)-numpy.nanstd(v),numpy.nanmean(v)-numpy.nanstd(v)],'r:')
        plt.xlabel('Steps')
        ylabel = ms
        if ms in list(plotname_assoc.keys()): ylabel = plotname_assoc[ms]
        plt.ylabel(ylabel)
    if stat in list(dp.columns):
        plt.subplot(int('{}1{}'.format(nplots,nplots)))
        v = []
        for dp in inp: v.extend(list(dp[stat].values))
        if isUnit(v[0]):
            v = [x.value for x in v]
        vp = [-0.5*(c-numpy.nanmin(v)) for c in v]
        yr = [numpy.min(vp),numpy.max(vp)]
        yr[0] -= 0.05*(yr[1]-yr[0])
        yr[1] += 0.05*(yr[1]-yr[0])
    #        print(yr)
        plt.xlim(xr)
        plt.ylim(yr)
        for dp in inp:
            plt.plot(numpy.arange(len(dp)),-0.5*(v-numpy.nanmin(v)),'k-',alpha=0.5)
        plt.xlabel('Steps')
        plt.ylabel('Statistic')

# save output
    if output != '':
        try:
            plt.savefig(output)
        except:
            print('\nProblem saving chains plot to {}'.format(output))
    return fig


def _modelFitMCMC_plotCorner(dp,**kwargs):
    '''
    :Purpose: Plots the parameter chains from an MCMC analysis (internal program)
    :param database: pandas DataFrame or list of DataFrames providing the parameters used to plot (required)
    :param columns: list of strings specifying which columns to plot (optional; default is all columns)
    :param burn: decimal fraction (0 to 1) of starting parameters to reject (optional; default = 0.)
    :param output: name of file for plotting chains (optional; alterate keywords file and filename)
    :param figsize: size of resulting figure (optional; default is set by number of parameters plotted)
    
    :Example:
    >>> import splat
    >>> import splat.model as spmod
    >>> sp = splat.getSpectrum(shortname='0415-0935')[0]
    >>> parameters = spmod.modelFitMCMC(sp,initial_guess=[800,5.0,0.0],nsamples=1000)
    >>> spmod._modelFitMCMC_plotChains(parameters,columns=['teff','logg','z'])
    '''

    try:
        import corner
    except:
        print('\nYou must install corner to display corner plot; see http://corner.readthedocs.io/en/latest/')
        return None

    plotname_assoc = {}
    for ms in SPECTRAL_MODEL_PARAMETERS_INORDER: plotname_assoc[ms] = '{} ({})'.format(SPECTRAL_MODEL_PARAMETERS[ms]['title'],SPECTRAL_MODEL_PARAMETERS[ms]['unit'])
    plotname_assoc['mass'] = r'Mass (M$_{\odot}$)'
    plotname_assoc['age'] = r'Age (Gyr)'
    plotname_assoc['luminosity'] = r'log L$_{bol}$/L$_{\odot}$'
    plotname_assoc['radius'] = r'Radius (R$_{\odot}$)'
    plotname_assoc['denisty'] = r'$\rho$ ($\rho_{\odot}$)'


# prep output
    output = kwargs.get('output','')
    output = kwargs.get('file',output)
    output = kwargs.get('filename',output)
    columns = kwargs.get('columns',list(dp.columns))

# make sure columns are all there - drop those that aren't
    tmp = []
    for c in columns:
        if c in list(dp.columns): tmp.append(c)

# go through and check that each column has some variability, and compute medians  
    cnames = []
    truths = []
    for c in tmp:
        v = list(dp[c])
        if isUnit(v[0]):
            dp[c] = [x.value for x in v]
        if numpy.nanstd(dp[c]) != 0.:
            cnames.append(c)
            truths.append(numpy.nanmedian(dp[c]))

# get labels all set
    labels = []
    for c in cnames: 
        if c in list(plotname_assoc.keys()):
            labels.append(plotname_assoc[c])
        else:
            labels.append(c)

#    if len(kwargs.get('truths',[])) == 0:
#        truths = [numpy.inf for i in range(samples.shape[-1])]

#    labels = [r''+SPECTRAL_MODEL_PARAMETERS[i]['title']+' ('+SPECTRAL_MODEL_PARAMETERS[i]['unit'].to_string()+')' for i in ['teff','logg','z'][:samples.shape[-1]-1]]
#    labels.append(r'Radius (R$_{\odot}$)')
    weights = kwargs.get('parameter_weights',numpy.ones(len(dp)))

    plt.clf()
    fig = corner.corner(dp.loc[:,cnames], quantiles=[0.16, 0.5, 0.84], truths=truths, \
            labels=labels, show_titles=True, weights=weights,\
            title_kwargs={"fontsize": kwargs.get('fontsize',12)})

# save output
    if output != '':
        try:
            plt.savefig(output)
        except:
            print('\nProblem saving corner plot to {}'.format(output))
    return fig

    try:
        fig.savefig(file)
    except:
        print('\nProblem saving corner plot to {}'.format(file))
    return fig



def _modelFitMCMC_reportResults(spec,dp,*arg,**kwargs):
    '''
    :Purpose: 
        Reports the result of model fitting parameters. Produces chain plot, corner plot, best fit model comparison and summarizes
        statistics of parameters

    Required Inputs:

        :param spec: Spectrum class object, which should contain wave, flux and noise array elements.
        :param dp: Must be an pandas DataFrame with columns containing parameters fit, and one column for chi-square values ('chisqr').
    
    Optional Inputs:
        :param evol: computes the mass, age, temperature, radius, surface gravity, and luminosity by using various evolutionary model sets. See below for the possible set options and the Brown Dwarf Evolutionary Models page for more details (default = True)
        :param emodel: set of evolutionary models to use; see `loadEvolModelParameters()`_ (default = 'Baraffe')

    .. _`loadEvolModelParameters()` : api.html#splat_evolve.loadEvolModel

        :param weight: set to True to use fitting statistic as a weighting to compute best fit statistics (default = True)
        :param stat: name of the statistics column in input table ``t`` (default = 'chisqr')
        :param stats: if True, prints several statistical values, including number of steps, best fit parameters, lowest chi2 value, median parameters and key values along the distribution (default = True)
        :param triangle: creates a triangle plot, plotting the parameters against each other, demonstrating areas of high and low chi squared values. Useful for demonstrating correlations between parameters (default = True)
        :param bestfit: set to True to plot best-fit model compared to spectrum (default=True)
        :param model_set: desired model set of ``bestfit``; see `loadModel()`_ for allowed options (can also use 'mset'; default = blank)

    .. _`loadModel()` : api.html#splat_model.loadModel

        :param filebase: a string that is the base filename for output (default = 'modelfit_results')
    
        :param sigma: when printing statistical results (``stats`` = True), print the value at ``sigma`` standard deviations away from the mean (default = 1)
        :param iterative: if True, prints quantitative results but does not plot anything (default = False)

    Output:
        No formal output, but results are plotted to various files

    :Example:
    >>> import splat
    >>> sp = splat.getSpectrum(shortname='1047+2124')[0]        # T6.5 radio emitter
    >>> spt, spt_e = splat.classifyByStandard(sp,spt=['T2','T8'])
    >>> teff,teff_e = splat.typeToTeff(spt)
    >>> sp.fluxCalibrate('MKO J',splat.typeToMag(spt,'MKO J')[0],absolute=True)
    >>> table = splat.modelFitMCMC(sp, mask_standard=True, initial_guess=[teff, 5.3, 0.], zstep=0.1, nsamples=100, savestep=0, verbose=False)
    >>> splat.reportModelFitResults(sp, table, evol = True, stats = True, sigma = 2, triangle = False)
        Number of steps = 169
        Best Fit parameters:
        Lowest chi2 value = 29567.2136599 for 169.0 degrees of freedom
        Effective Temperature = 918.641 (K)
        log Surface Gravity = 5.211 
        Metallicity = 0.000 
        Radius (relative to Sun) from surface fluxes = 0.096 
        <BLANKLINE>
        Median parameters:
        Effective Temperature = 927.875 + 71.635 - 73.237 (K)
        log Surface Gravity = 5.210 + 0.283 - 0.927 
        Metallicity = 0.000 + 0.000 - 0.000 
        Radius (relative to Sun) from surface fluxes = 0.108 + 0.015 - 0.013 
    '''

    evolFlag = kwargs.get('evol',True)
    emodel = kwargs.get('emodel','Baraffe')
    statsFlag = kwargs.get('stats',True)
    triangleFlag = kwargs.get('triangle',True)
    bestfitFlag = kwargs.get('bestfit',True)
    summaryFlag = kwargs.get('summary',True)
    weights = kwargs.get('weight',None)
    filebase = kwargs.get('filebase','modelfit_results')
    statcolumn = kwargs.get('stat','chisqr')
    mset = kwargs.get('model_set','')
    mset = kwargs.get('mset',mset)
    mask_ranges = kwargs.get('mask_ranges',[])
    sigma = kwargs.get('sigma',1.)

# map some common column names to full descriptive texts
    plotname_assoc = {\
        'teff': r'T$_{eff}$',\
        'logg': r'log g',\
        'z': r'[M/H]',\
        'mass': r'M/M$_{\odot}$',\
        'age': r'$\tau$',\
        'lbol': r'log L$_{bol}$/L$_{\odot}$',\
        'radius': r'R/R$_{\odot}$',\
        'radius_evol': r'R/R$_{\odot}$'}

    format_assoc = {\
        'teff': '.0f',\
        'logg': '.2f',\
        'z': '.2f',\
        'mass': '.3f',\
        'age': '.1f',\
        'lbol': '.2f',\
        'radius': '.3f',\
        'radius_evol': '.3f'}

    descrip_assoc = {\
        'teff': 'Effective Temperature',\
        'logg': 'log Surface Gravity',\
        'z': 'Metallicity',\
        'mass': 'Mass',\
        'age': 'Age',\
        'lbol': 'log Luminosity (relative to Sun)',\
        'radius': 'Radius (relative to Sun) from surface fluxes',\
        'radius_evol': 'Radius (relative to Sun) from evolutionary models'}

    unit_assoc = {\
        'teff': 'K',\
#        'logg': r'cm/s$^2$',\
        'age': 'Gyr'}

    if kwargs.get('iterative',False):
        statsFlag = True
        evolFlag = True
        triangleFlag = False
        bestfitFlag = False
        summaryFlag = False

# check that table has the correct properties
    if isinstance(t,Table) == False:
        raise ValueError('\nInput is not an astropy table')
    if len(t.columns) < 2:
        raise ValueError('\nNeed at least two columns in input table')
    if statcolumn not in t.colnames:
        raise ValueError('\n{} column must be present in input table'.format(statcolumn))

    parameters = t.colnames
    parameters.remove(statcolumn)
 
# get the evolutionary model parameters
# turned off for now
#    evolFlag = False
#    if evolFlag:
#        if 'teff' not in t.colnames or 'logg' not in t.colnames:
#            print('\nCannot compare to best fit without teff and logg parameters')
#
#        else:
#            values=bdevopar.Parameters(emodel, teff=t['teff'], grav=t['logg'])
#            t['age'] = values['age']
#            t['lbol'] = values['luminosity']
#            t['mass'] = values['mass']
#            t['radius_evol'] = values['radius']
#            parameters = t.colnames
#            parameters.remove(statcolumn)
    
   
# calculate statistics
    if statsFlag:
        if weights == True:
            weights = numpy.exp(0.5*(numpy.nanmin(t[statcolumn])-t[statcolumn]))

        print('\nNumber of steps = {}'.format(len(t)))
        
        print('\nBest Fit parameters:')
        print('Lowest chi2 value = {} for {} degrees of freedom'.format(numpy.nanmin(t[statcolumn]),spec.dof))
        for p in parameters:
            sort = [x for (y,x) in sorted(zip(t[statcolumn],t[p]))]
            name = p
            if p in descrip_assoc.keys():
                name = descrip_assoc[p]
            unit = ''
            if p in unit_assoc.keys():
                unit = '('+unit_assoc[p]+')'
            print('{} = {:.3f} {}'.format(name,sort[0],unit))

        print('\nMedian parameters:')
        for p in parameters:
            sm, mn, sp = distributionStats(t[p],sigma=sigma,weights=weights)      # +/- 1 sigma
            name = p
            if p in descrip_assoc.keys():
                name = descrip_assoc[p]
            unit = ''
            if p in unit_assoc.keys():
                unit = '('+unit_assoc[p]+')'
            print('{} = {:.3f} + {:.3f} - {:.3f} {}'.format(name,mn,sp-mn,mn-sm,unit))
        print('\n')

        
# best fit model
    if bestfitFlag and mset in list(SPECTRAL_MODELS.keys()):
# check to make sure at least teff & logg are present
        if 'teff' not in t.colnames or 'logg' not in t.colnames:
            print('\nCannot compare to best fit without teff and logg parameters')

        else:
            t.sort(statcolumn)
            margs = {'set': mset, 'teff': t['teff'][0], 'logg': t['logg'][0]}
            legend = [spec.name,'{} T = {:.0f}, logg =  {:.2f}'.format(mset,margs['teff'],margs['logg']),r'$\chi^2$ = {:.0f}, DOF = {:.0f}'.format(t[statcolumn][0],spec.dof)]
            if 'z' in t.colnames:
                margs['z'] = t['z'][0]
                legend[1]+=', z = {:.2f}'.format(margs['z'])
            model = loadModel(**margs)
            chisqr,alpha = compareSpectra(spec, model ,mask_ranges=mask_ranges)
            model.scale(alpha)

            w = numpy.where(numpy.logical_and(spec.wave.value > 0.9,spec.wave.value < 2.35))
            diff = spec-model
            print(filebase)
            splot.plotSpectrum(spec,model,diff,uncertainty=True,telluric=True,colors=['k','r','b'], \
                legend=legend,filename=filebase+'bestfit.eps',\
                yrange=[1.1*numpy.nanmin(diff.flux.value[w]),1.25*numpy.nanmax([spec.flux.value[w],model.flux.value[w]])])  
 
# triangle plot of parameters
    if triangleFlag:
        y=[]
        labels = []
        fmt = []
        for p in parameters:
            if min(numpy.isfinite(t[p])) == True and numpy.nanstd(t[p]) != 0.:       # patch to address arrays with NaNs in them
                y.append(t[p])
                if p in plotname_assoc.keys():
                    labels.append(plotname_assoc[p])
                else:
                    labels.append(p)
                if p in unit_assoc.keys():
                    labels[-1] = labels[-1]+' ('+unit_assoc[p]+')'
                if p in format_assoc.keys():
                    fmt.append(format_assoc[p])
                else:
                    fmt.append('.2f')
#        print(labels)
        print(labels, fmt)
        fig = triangle.corner(zip(*y[::-1]), labels=list(reversed(labels)), show_titles=True, quantiles=[0.16,0.5,0.84],cmap=cm.Oranges,title_fmt=list(reversed(fmt)),plot_contours=True)
        fig.savefig(filebase+'parameters.eps')
        fig.clf()
           
# plain language summary
    if summaryFlag:
        pass

    return
            


#######################################################
#######################################################
###############   EMCEE MODEL FITTING  ################
#######################################################
#######################################################



def modelFitEMCEE(specin, mset='BTSettl2008', instrument='SPEX-PRISM', initial={}, nofit = [], nwalkers=10, nsamples=100, threads=1, burn=0.5, propose_scale=1.1, verbose=False, **kwargs):
    '''
    :Purpose: Uses the ``emcee`` package by Dan Foreman-Mackey et al. to perform 
        Goodman & Weare's Affine Invariant Markov chain Monte Carlo (MCMC) Ensemble sampler
        to fit a spectrum to a set of atmosphere models. 
        Returns the best estimate of the effective temperature, surface 
        gravity, and (if selected) metallicity.  Includes an estimate of the time required to run, prompts
        user if they want to proceed, and shows progress with iterative saving of outcomes
    :param spec: Spectrum class object, which should contain wave, flux and noise array elements (required)
    :param nwalkers: number of MCMC walkers, should be at least 20 (optional, default = 20)
    :param nsamples: number of MCMC samples (optional, default = 500)
    :param threads: number of threads to run on a multiprocessing machine (optional, default = 1)
    :param burn_fraction: the fraction of the initial steps to be discarded; e.g., if 
                ``burn_fraction = 0.2``, the first 20% of the samples are discarded. (optional, default = 0.5)
    :param initial_guess: array including initial guess of the model parameters.
            Can also set individual guesses of spectral parameters by using 
            **initial_temperature**, **initial_teff**, or **t0**;
            **initial_gravity**, **initial_logg** or **g0**; 
            and **initial_metallicity**, **initial_z** or **z0** (optional, default = array of random numbers within allowed ranges)
    :param limits: list of 2-element arrays indicating ranges of the model parameters to limit the parameter space.
            Can also set individual ranges of spectral parameters by using 
            **temperature_range**, **teff_range** or **t_range**;
            **gravity_range**, **logg_range** or **g_range**;
            and **metallicity_range** or **z_range** (optional, default = depends on model set)
    :param prior_scatter: array giving the widths of the normal distributions from which to draw prior parameter values (optional, default = [25,0.1,0.1])
    :param model: set of models to use (``set`` and ``model_set`` do the same); options include:

        - *'BTSettl2008'*: model set with effective temperature of 400 to 2900 K, surface gravity of 3.5 to 5.5 and metallicity of -3.0 to 0.5 
          from `Allard et al. (2012) <http://adsabs.harvard.edu/abs/2012RSPTA.370.2765A>`_
        - *'burrows06'*: model set with effective temperature of 700 to 2000 K, surface gravity of 4.5 to 5.5, metallicity of -0.5 to 0.5, 
          and sedimentation efficiency of either 0 or 100 from `Burrows et al. (2006) <http://adsabs.harvard.edu/abs/2006ApJ...640.1063B>`_
        - *'morley12'*: model set with effective temperature of 400 to 1300 K, surface gravity of 4.0 to 5.5, metallicity of 0.0 
          and sedimentation efficiency of 2 to 5 from `Morley et al. (2012) <http://adsabs.harvard.edu/abs/2012ApJ...756..172M>`_
        - *'morley14'*: model set with effective temperature of 200 to 450 K, surface gravity of 3.0 to 5.0, metallicity of 0.0 
          and sedimentation efficiency of 5 from `Morley et al. (2014) <http://adsabs.harvard.edu/abs/2014ApJ...787...78M>`_
        - *'saumon12'*: model set with effective temperature of 400 to 1500 K, surface gravity of 3.0 to 5.5 and metallicity of 0.0 
          from `Saumon et al. (2012) <http://adsabs.harvard.edu/abs/2012ApJ...750...74S>`_
        - *'drift'*: model set with effective temperature of 1700 to 3000 K, surface gravity of 5.0 to 5.5 and metallicity of -3.0 to 0.0 
          from `Witte et al. (2011) <http://adsabs.harvard.edu/abs/2011A%26A...529A..44W>`_
    
    :type model: optional, default = 'BTSettl2008'
    :param radius: set to True to calculate and returns radius of object [NOT CURRENT IMPLEMENTED]
    :type radius: optional, default = False
    :param save: save interim results to a .dat file based on output filename
    :type save: optional, default = True
    :param output: base filename for output (``filename`` and ``outfile`` do the same); 
        outputs will include (each can be set individually with associated keywords):
        - ``filename_iterative.dat``: interative saved data
        - ``filename_summary.txt``: summary of results
        - ``filename_corner.eps``: corner plot of parameters
        - ``filename_comparison.eps``: plot spectrum compared to best fit model
    :type output: optional, default = None
    :param plot_format: file type for diagnostic plots
    :type plot: optional, default = 'pdf'
    :param noprompt: don't prompt user to continue of emcee run will be > 10 minutes
    :type noprompt: optional, default = False
    :param verbose: give lots of feedback
    :type verbose: optional, default = False

    In addition, the parameters for compareSpectra_, generateMask_, plotSpectrum_; see SPLAT API for details.

    .. _plotSpectrum: api.html#splat_plot.plotSpectrum
    .. _plotSpectrum: api.html#splat.compareSpectra
    .. _generateMask api.html#splat.generateMask
    
    Note: modelfitEMCEE requires external packages: 
        - ``emcee``: http://dan.iel.fm/emcee/current
        -``corner``: http://corner.readthedocs.io/en/latest

    :Example:
    >>> import splat
    >>> sp = splat.Spectrum(shortname='1507-1627')[0]
    >>> spt,spt_e = splat.classifyByStandard(sp)
    >>> teff,teff_e = splat.typeToTeff(spt)
    >>> result = modelFitEMCEE(sp,t0=teff,g0=5.0,fit_metallicity=False,\
    >>>    nwalkers=50,nsamples=500,output='/Users/adam/test_modelfitEMCEE')
        Estimated time to compute = 9228 seconds = 153.8 minutes = 2.56 hours = 0.11 days
        Do you want to continue? [Y/n]: 
        Progress: [**************************************************]
    
    Results are saved in test_modelfitEMCEE_interative.dat, *_chains.pdf, *_comparison.pdf, *_corner.pdf, and *_summary.txt
    '''

# check that emcee package is installed
    try:
        import emcee
    except:
        raise NameError('\nYou must install emcee to run this program; see http://dan.iel.fm/emcee/current/')

    start_time = time.time()

# keywords
#    nwalkers = kwargs.get('nwalkers', 10)
#    nsamples = kwargs.get('nsamples', 1000)
#    threads = kwargs.get('threads', 1)
    burn_fraction = kwargs.get('burn_fraction', burn)  # what fraction of the initial steps are to be discarded
    propose_scale = kwargs.get('scale', propose_scale)  # emcee scale factor
#    verbose = kwargs.get('verbose', False)
    feedback_width = 50

# plotting and reporting keywords
    showRadius = False
    try: showRadius = (spec.fscale == 'Absolute')
    except: pass
    showRadius = kwargs.get('radius', showRadius)
    filebase = kwargs.get('output', 'fit_')
    filebase = kwargs.get('filename',filebase)
    filebase = kwargs.get('outfile',filebase)
    plot_format = kwargs.get('plot_format','pdf')

# prep outputs
    file_iterative = kwargs.get('file_iterative',os.path.splitext(filebase)[0]+'_iterative.dat')
    file_chains = kwargs.get('file_chains',os.path.splitext(filebase)[0]+'_chains.'+plot_format)
    file_corner = kwargs.get('file_corner',os.path.splitext(filebase)[0]+'_corner.'+plot_format)
    file_comparison = kwargs.get('file_comparison',os.path.splitext(filebase)[0]+'_comparison.'+plot_format)
    file_bestcomparison = kwargs.get('file_bestcomparison',os.path.splitext(filebase)[0]+'_bestcomparison.'+plot_format)
    file_summary = kwargs.get('file_summary',os.path.splitext(filebase)[0]+'_summary.txt')
    if kwargs.get('save',True):
        f = open(file_iterative,'w')
        f.close()

# check model name
    modelset = kwargs.get('model', modelset)
    modelset = kwargs.get('set', modelset)
    modelset = kwargs.get('model_set', modelset)
    mset = checkSpectralModelName(modelset)
    if mset == False:
        raise ValueError('\n{} is not in the SPLAT model suite; try {}'.format(modelset,' '.join(list(SPECTRAL_MODELS.keys()))))
    if verbose == True:
        print('\nmodelFitGrid is using {} model set'.format(mset))
        kwargs['summary'] = True

# check instrument name
    instrument = kwargs.get('instr',instrument)
    try:
        if instrument == '': instrument = specin.instrument
    except:
        pass
    instr = checkInstrument(instrument)
    if instr == False: instr=instrument
    if verbose == True: print('modelFitGrid is using {} instrument'.format(instr))

# make sure instrument computed for model set
    if instr not in list(SPECTRAL_MODELS[mset]['instruments']):
        raise ValueError('{} models for instrument {} have not been computed; run processModelsToInstrument()'.format(mset,instr))

# copy of spectrum
    spec = copy.deepcopy(specin)


# grab model parameters
    modelgrid = _loadModelParameters(mset,instrument) # Range parameters can fall in

# read in available model grid points
    gridparam = _loadModelParameters(mset,instr) 

# populate ranges - ONLY CONTINUOUS AND NOT IN "NOFIT"
    ranges = {}
    for ms in list(SPECTRAL_MODEL_PARAMETERS.keys()):
        if ms in list(gridparam.keys()):
            if SPECTRAL_MODEL_PARAMETERS[ms]['type'] == 'continuous' and ms not in nofit and SPECTRAL_MODEL_PARAMETERS[ms]['name'] not in nofit and SPECTRAL_MODEL_PARAMETERS[ms]['prefix'] not in nofit:
                rng = kwargs.get('{}_range'.format(ms),[numpy.min(gridparam[ms]),numpy.max(gridparam[ms])])
                rng = kwargs.get('{}_range'.format(SPECTRAL_MODEL_PARAMETERS[ms]['name']),rng)
                rng = kwargs.get('{}_range'.format(SPECTRAL_MODEL_PARAMETERS[ms]['prefix']),rng)
                ranges[ms] = rng
#                if ms == 'z' and kwargs.get('nometallicity',False) == True: ranges[ms] = [0,0]

# establish initial parameter set; if not provided, chose a value in middle of range
    for ms in list(ranges.keys()):
        if ms not in list(initial.keys()): initial[ms] = numpy.median(gridparam[ms])


########## STOPPED HERE ##########


# THESE NEED TO BE CHANGED TO ACCOMODATE NEW MODEL FORMAT
    prior_scale = {'teff': 25, 'logg': 0.1, 'z': 0.1, 'radius': 0.001*const.R_sun.value}
    prior_scale['teff'] = kwargs.get('t_scale',prior_scale['teff'])
    prior_scale['logg'] = kwargs.get('g_scale',prior_scale['logg'])
    prior_scale['z'] = kwargs.get('z_scale',prior_scale['z'])


# create a mask
    mask = kwargs.get('mask',generateMask(spec.wave,**kwargs))

# set initial parameters
    # parameters0 = kwargs.get('initial_guess',[\
    #     numpy.random.uniform(teff_range[0],teff_range[1]),\
    #     numpy.random.uniform(logg_range[0],logg_range[1]),\
    #     0.0])
    # if len(parameters0) < 3:
    #     parameters0.append(0.0)
        
    # parameters0[0] = kwargs.get('initial_temperature',parameters0[0])
    # parameters0[0] = kwargs.get('initial_teff',parameters0[0])
    # parameters0[0] = kwargs.get('t0',parameters0[0])
    # parameters0[1] = kwargs.get('initial_gravity',parameters0[1])
    # parameters0[1] = kwargs.get('initial_logg',parameters0[1])
    # parameters0[1] = kwargs.get('g0',parameters0[1])
    # parameters0[2] = kwargs.get('initial_metallicity',parameters0[2])
    # parameters0[2] = kwargs.get('initial_z',parameters0[2])
    # parameters0[2] = kwargs.get('z0',parameters0[2])

    # mflag = kwargs.get('fit_metallicity',False)
    # mflag = kwargs.get('fitmetallicity',mflag)
    # if not mflag: parameters0 = parameters0[0:2]

    # parameter_names = ['teff','logg','z'][:len(parameters0)]
    # parameter_titles = [SPECTRAL_MODEL_PARAMETERS[p]['title'] for p in parameter_names]
    # parameter_units = [SPECTRAL_MODEL_PARAMETERS[p]['unit'] for p in parameter_names]
    # nparameters = len(parameters0)


# initialize with modelFitGrid
    if kwargs.get('initialize',False) == True:
        if verbose: print('Running an initialization step')
        param = modelFitGrid(spec,**kwargs)
        parameters0 = [param[f] for f in parameter_names]

# initial scatter
    pscale = [prior_scale[p] for p in parameter_names]
    initial_parameters = [parameters0+pscale*numpy.random.randn(len(parameters0)) for i in range(nwalkers)]

# check the time it should take to run model, and that user has models
    testtimestart = time.time()
    try: mdl = loadModel(teff=parameters0[0],logg=parameters0[1],set=mset,instrument=instrument)
    except: raise ValueError('\nProblem reading in a test model; make sure you have the full SPLAT model set installed')
    try: mdl = loadModel(teff=parameters0[0]+20.,logg=parameters0[1]+0.1,set=mset)
    except: pass
    testtimeend = time.time()
    time_estimate = (testtimeend-testtimestart)*nwalkers*nsamples*1.2/(1.*threads)
#    print(testtimeend,testtimestart)
    print('Estimated time to compute = {:.0f} seconds = {:.1f} minutes = {:.2f} hours'.\
        format(time_estimate,time_estimate/60.,time_estimate/3600.))
    if time_estimate > 1200. and not kwargs.get('noprompt',False):
        resp = input('Do you want to continue? [Y/n]: ')
        if resp.lower()[0] == 'n':
            print('\nAborting')
            return

# run EMCEE with iterative saving and updates
    testtimestart = time.time()
    model_params = {'model': mset, 'instrument': instrument, 'limits': limits, 'mask': mask}
    sampler = emcee.EnsembleSampler(nwalkers, nparameters, _modelFitEMCEE_lnprob, threads=threads, args=(spec.wave.value,spec.flux.value,spec.noise.value,model_params),a=propose_scale)
    sys.stdout.write("\n")
    for i, result in enumerate(sampler.sample(initial_parameters, iterations=nsamples)):
        if i > 0:
            ch = sampler.chain[:,:i,:]
            radii = ((sampler.blobs[:i]*(kwargs.get('distance',10.)*u.pc.to(u.cm)/const.R_sun)**2)**0.5).value.reshape(-1)
            cr = ch.reshape((-1, nparameters))
            mcr = numpy.append(cr.transpose(),[radii],axis=0).transpose()
            lnp = sampler.lnprobability[:,:i].reshape(-1)
            if verbose: print(lnp)
            if kwargs.get('use_weights',False) != False:
                parameter_weights = numpy.exp(lnp-numpy.max(lnp))
            else:
                parameter_weights = numpy.ones(len(lnp))
            bparam,mparam,qparam = _modelFitEMCEE_bestparameters(mcr,lnp,parameter_weights=parameter_weights)
            if verbose: print(bparam,mparam,qparam)
    #        lnp = result[1]
    #        scales = result[-1]
    #        radii = ((scales*(kwargs.get('distance',10.)*u.pc.to(u.cm)/const.R_sun)**2)**0.5).value.reshape(-1)
            n = int((feedback_width+1) * float(i) / nsamples)
            resp = '\rProgress: [{0}{1}] '.format('*' * n, ' ' * (feedback_width - n))
            for i,kkk in enumerate(['teff','logg','z'][:nparameters]):
                resp+=' {:s}={:.2f}'.format(SPECTRAL_MODEL_PARAMETERS[kkk]['title'],bparam[i])
            resp+=' R={:.2f} lnP={:e}'.format(bparam[-1],lnp[-1])
            print(resp)
    # save iteratively
            position = result[0]
            if verbose: print(position)
            if kwargs.get('save',True) and i > 5:
                _modelFitEMCEE_plotchains(ch,file_chains)
                _modelFitEMCEE_plotcomparison(cr,spec,file_comparison,model=mset,draws=5,parameter_weights=parameter_weights)
                _modelFitEMCEE_plotbestcomparison(spec,bparam[:-1],file_bestcomparison,model=mset)
#                _modelFitEMCEE_plotcorner(mcr,file_corner,parameter_weights=parameter_weights,**kwargs)
                f = open(file_iterative, 'a')
                for k in range(position.shape[0]):
                    f.write('{0:4d} {1:s} {2:e}\n'.format(k, ' '.join([str(mmm) for mmm in position[k]]),lnp[k]))
                f.close()
    sys.stdout.write("\n")

# burn out the initial section
    orig_samples = sampler.chain.reshape((-1, nparameters))
    orig_lnp = sampler.lnprobability.reshape(-1)
    orig_radii = ((numpy.array(sampler.blobs).reshape(-1)*(kwargs.get('distance',10.)*u.pc.to(u.cm)/const.R_sun)**2)**0.5).value.reshape(-1)
    samples = sampler.chain[:, int(burn_fraction*nsamples):, :].reshape((-1, nparameters))
    lnp = orig_lnp[int(burn_fraction*nsamples*nwalkers):]
    radii = orig_radii[int(burn_fraction*nsamples*nwalkers):]
    merged_samples = numpy.append(samples.transpose(),[radii],axis=0).transpose()

    if verbose: print(orig_radii.shape,orig_samples.shape,orig_lnp.shape)
    if verbose: print(radii.shape,samples.shape,lnp.shape,sampler.chain.shape)

# determine parameters
    if kwargs.get('use_weights',False) != False:
        parameter_weights = numpy.exp(lnp-numpy.max(lnp))
    else:
        parameter_weights = numpy.ones(len(lnp))

    bparam,mparam,qparam = _modelFitEMCEE_bestparameters(merged_samples,lnp,parameter_weights=parameter_weights)
    if verbose: print(bparam)

# check time
    testtimeend = time.time()
    time_estimate = (testtimeend-testtimestart)
#    print(testtimeend,testtimestart)
    print('Actual time to compute = {:.0f} seconds = {:.1f} minutes = {:.2f} hours'.\
        format(time_estimate,time_estimate/60.,time_estimate/3600.))

# reporting
    _modelFitEMCEE_plotchains(sampler.chain,file_chains)
#    _modelFitEMCEE_plotcomparison(samples,spec,file_comparison,model=model_set,draws=20,parameter_weights=parameter_weights,**kwargs)
#    _modelFitEMCEE_plotbestcomparison(spec,bparam[:-1],file_bestcomparison,model=model_set,**kwargs)
    _modelFitEMCEE_plotcorner(merged_samples,file_corner,parameter_weights=parameter_weights,**kwargs)

    end_time = time.time()
    total_time = (end_time-start_time)
    if verbose: print('Total run time = {:.0f} seconds or {:.2f} hours'.format(total_time,total_time/3600.))

    skwargs = {'burn_fraction': burn_fraction, 'filebase': filebase, 'total_time': total_time, 'mask': mask, 'model': mset, 'instrument': instrument}
    _modelFitEMCEE_summary(sampler,spec,file_summary,**skwargs)
    return sampler



def _modelFitEMCEE_bestparameters(values,lnp,**kwargs):
    '''
    Return three sets of parameters: by quantiles, the weighted mean, and the best values
    '''
    parameter_weights = kwargs.get('parameter_weights',numpy.ones(values.shape[-1]))
    quantiles = kwargs.get('quantiles',[16,50,84])
    verbose = kwargs.get('verbose',False)

    quant_parameters = []
    best_parameters = []
    mean_parameters = []
    for i in range(values.shape[-1]):
        q = numpy.percentile(values[:,i],quantiles)
        quant_parameters.append([q[1],q[2]-q[1],q[1]-q[0]])
        mean_parameters.append(numpy.sum(parameter_weights*values[:,i])/numpy.sum(parameter_weights))
        best_parameters.append(values[numpy.where(lnp == numpy.max(lnp)),i].reshape(-1)[0])
    return best_parameters,mean_parameters,quant_parameters


def _modelFitEMCEE_lnlikelihood(theta,x,y,yerr,model_params):
    verbose = False
    mparam = copy.deepcopy(model_params)
    for i,v in enumerate(['teff','logg','z'][0:len(theta)]):
        mparam[v] = theta[i]
    try:
        mdl = loadModel(**mparam)
    except:
        resp = '\nProblem reading in model '
        for k,v in enumerate(theta):
            resp+='{} = {}, '.format(['teff','logg','z'][k],v)
        print(resp)
        return -1.e30,0.
#    chi,scl = splat.compareSpectra(sp,mdl,**model_params)
    chi,scl = compareSpectra(Spectrum(wave=x,flux=y,noise=yerr),mdl,**model_params)
    lnp = -0.5*chi
    if model_params.get('noise_scaling',False):
        f = interp1d(mdl.wave.value,mdl.flux.value*scl,bounds_error=False,fill_value=0.)
        inv_sigma2 = 1./(yerr**2+f(x)**2*numpy.exp(theta[-1]))
        lnp = -0.5*numpy.nansum((1.-mparam['mask'])*((y-f(x))**2*inv_sigma2-numpy.log(inv_sigma2)))
#            inv_sigma2 = 1./yerr**2
#            lnp = -0.5*numpy.nansum((y-f(x))**2*inv_sigma2)
    return lnp,scl
#    except:
#        resp = '\nProblem comparing model '
#        for k,v in enumerate(theta):
#            resp+='{} = {}, '.format(MODEL_PARAMETER_NAMES[k],v)
#        print(resp+' to data')
#    return -numpy.inf


def _modelFitEMCEE_lnprior_limits(theta,limits):
    '''
    compute the log of the probability assuming a uniform distribution
    with hard limits; if outside limits, probability returns -infinity
    '''
    for i,t in enumerate(theta):
        try:
            if t < numpy.min(limits[i]) or t > numpy.max(limits[i]):
                return -1.e30
        except:
            pass
    return 0.0


def _modelFitEMCEE_lnprior_normal(theta,meansds):
    '''
    compute the log of the probability assuming a normal distribution
    there probably needs to be better error checking here
    '''
    lnp = 0.0
    for i,t in enumerate(theta):
        try:
            lnp-=0.5*(((t-meansds[i][0])/meansds[i][1])**2-numpy.log(meansds[i][1]))
        except:
            pass
    return lnp

def _modelFitEMCEE_lnprob(theta,x,y,yerr,model_params):
#    lnp = 0.
#    if kwargs.get('normal_priors',None) != None and kwargs.get('priors_meansds',None) != None:
#        lnp+=modelFitEMCEE_lnprior_normal(theta,kwargs.get('priors_meansds'),**kwargs)
#    if kwargs.get('limits',None) != None:
    lnp0 = _modelFitEMCEE_lnprior_limits(theta,model_params['limits'])
    if not numpy.isfinite(lnp0):
        return -1.e30
    lnp,scale = _modelFitEMCEE_lnlikelihood(theta,x,y,yerr,model_params)
    return lnp0+lnp, scale


def _modelFitEMCEE_plotchains(chains,file,**kwargs):
    plt.figure(1,figsize=kwargs.get('figsize',[8,4*chains.shape[-1]]))
    mplabels = ['teff','logg','z']
    for i in range(chains.shape[-1]):
        plt.subplot(int('{}1{}'.format(chains.shape[-1],i+1)))
        xr = [0,chains.shape[1]-1]
        yr = [numpy.min(chains[:,:,i]),numpy.max(chains[:,:,i])]
        yr[0] -= 0.05*(numpy.max(chains[:,:,i])-numpy.min(chains[:,:,i]))
        yr[1] += 0.05*(numpy.max(chains[:,:,i])-numpy.min(chains[:,:,i]))
#        print(yr)
        for j in range(chains.shape[0]):
            plt.plot(numpy.arange(chains.shape[1]),chains[j,:,i],'k-',alpha=0.4)
        if kwargs.get('burn_fraction',0) > 0:
            plt.plot([chains.shape[1]*kwargs.get('burn_fraction')]*2,yr,'k:')
            mn = numpy.mean(chains[:,chains.shape[1]*kwargs.get('burn_fraction'):,i])
        else:
            mn = numpy.mean(chains[:,:,i])
        plt.axis(xr+yr)
        plt.plot(xr,[mn]*2,'r-')
        plt.xlabel('Steps')
        plt.ylabel(r''+SPECTRAL_MODEL_PARAMETERS[mplabels[i]]['title']+' ('+SPECTRAL_MODEL_PARAMETERS[mplabels[i]]['unit'].to_string()+')')
    try:
        plt.savefig(file)
        plt.clf()
    except:
        print('\nProblem saving chains plot to {}'.format(file))
    return plt


def _modelFitEMCEE_plotcomparison(samples,spec,file,**kwargs):
    '''
    for now just plotting best model
    would like to do draws from posterior instead
    '''
# extract best fit values
    mplabels = ['teff','logg','z']
    draws = kwargs.get('draws',1)
    pargs = (spec,)
    legend = [spec.name]
    colors = ['k']
    alpha = [0]
    tbl = Table()
    tbl['parameter_weights'] = kwargs.get('parameter_weights',numpy.ones(samples.shape[0]))
    tbl['parameter_weights'] = numpy.max(tbl['parameter_weights'])-tbl['parameter_weights']
    for i in range(samples.shape[-1]):
        tbl[mplabels[i]] = samples[:,i]
    tbl.sort('parameter_weights')
    tblu = tunique(tbl,keys=mplabels[i][:samples.shape[-1]])
    draws = numpy.min([draws,len(tblu)])
    for k in range(draws):
        mkwargs = copy.deepcopy(kwargs)
        mlegend = r''
        for i in range(samples.shape[-1]):
            mkwargs[mplabels[i]] = tblu[mplabels[i]][k]
            mlegend+='{:s}={:.2f} '.format(SPECTRAL_MODEL_PARAMETER[mplabels[i]]['title'],mkwargs[mplabels[i]])
        mdl = loadModel(**mkwargs)
#    print(mdl.teff,mdl.logg)
        stat,scl = compareSpectra(spec,mdl,**kwargs)
        mdl.scale(scl)
        pargs = pargs + (mdl,)
        legend.append(mlegend)
        colors.append('grey')
        alpha.append(tblu['parameter_weights'][k])
#    print(*pargs)
    return splot.plotSpectrum(*pargs,colors=colors,alpha=alpha,\
        uncertainty=True,telluric=True,file=file,legend=legend)


def _modelFitEMCEE_plotbestcomparison(spec,mparam,file,**kwargs):
    '''
    for now just plotting best model
    would like to do draws from posterior instead
    '''

# extract best fit values
    mplabels = ['teff','logg','z']
    mkwargs = copy.deepcopy(kwargs)
    mlegend = r''
#    print(mparam)
    for i,m in enumerate(mparam):
        mkwargs[mplabels[i]] = m
        mlegend+='{:s}={:.2f} '.format(SPECTRAL_MODEL_PARAMETERS[mplabels[i]]['title'],float(m))
#    print(mkwargs)
    mdl = loadModel(**mkwargs)
#    print(mdl.teff,mdl.logg)
    stat,scl = compareSpectra(spec,mdl,**kwargs)
    mdl.scale(scl)
    return splot.plotSpectrum(spec,mdl,spec-mdl,colors=['k','b','grey'],uncertainty=True,telluric=True,file=file,\
        legend=[spec.name,mlegend,r'difference ($\chi^2$ = {:.0f})'.format(stat)])



def _modelFitEMCEE_plotcorner(samples,file,**kwargs):
    '''
    corner plot for modelFitEMCEE
    '''
    try:
        import corner
    except:
        print('\nYou must install corner to display corner plot; see http://corner.readthedocs.io/en/latest/')
        return None

    if len(kwargs.get('truths',[])) == 0:
        truths = [numpy.inf for i in range(samples.shape[-1])]

    labels = [r''+SPECTRAL_MODEL_PARAMETERS[i]['title']+' ('+SPECTRAL_MODEL_PARAMETERS[i]['unit'].to_string()+')' for i in ['teff','logg','z'][:samples.shape[-1]-1]]
    labels.append(r'Radius (R$_{\odot}$)')
    weights = kwargs.get('parameter_weights',numpy.ones(samples.shape[0]))

    fig = corner.corner(samples, quantiles=[0.16, 0.5, 0.84], truths=truths, \
            labels=labels, show_titles=True, weights=weights,\
            title_kwargs={"fontsize": kwargs.get('fontsize',12)})

    try:
        fig.savefig(file)
        fig.clf()
    except:
        print('\nProblem saving corner plot to {}'.format(file))
    return fig


def _modelFitEMCEE_summary(sampler,spec,file,**kwargs):
    '''
    for now just plotting best model
    would like to do draws from posterior instead
    '''

# extract best fit values
    base_samples = sampler.chain
    nwalkers = base_samples.shape[0]
    nsamples = base_samples.shape[1]
    nparameters = base_samples.shape[2]
    samples = base_samples[:, int(kwargs['burn_fraction']*nsamples):, :].reshape((-1, nparameters))

    f = open(file,'w')
    f.write('EMCEE fitting analysis of spectrum of {} using the models of {}'.format(spec.name,kwargs['model']))
    f.write('\nFitting performed on {}'.format(time.strftime("%Y %h %d %I:%M:%S")))
    f.write('\n\nMCMC paramaters:')
    f.write('\n\tNumber of walkers = {}'.format(nwalkers))
    f.write('\n\tNumber of samples = {}'.format(nsamples))
    f.write('\n\tNumber of fit parameters = {}'.format(nparameters))
    f.write('\n\tBurn-in fraction = {}'.format(kwargs['burn_fraction']))

    f.write('\n\nBest fit parameters')
    for i,v in enumerate(['teff','logg','z'][0:nparameters]):
        fit = numpy.percentile(samples[:,i], [16, 50, 84])
        f.write('\n\t{} = {}+{}-{} {}'.format(SPECTRAL_MODEL_PARAMETERS[v]['title'],fit[1],fit[2]-fit[1],fit[1]-fit[0],SPECTRAL_MODEL_PARAMETERS[v]['unit'].to_string()))

    mkwargs = copy.deepcopy(kwargs)
    for i,l in enumerate(['teff','logg','z'][:samples.shape[-1]]):
        mkwargs[l] = numpy.median(samples[:,i])
    mdl = loadModel(**mkwargs)
    stat,scl = compareSpectra(spec,mdl,**kwargs)

# copmute DOF
    try:
        dof = spec.dof
    except:
        dof = len(spec.wave)
    if len(kwargs.get('mask',[])) > 0:
        dof = dof*(numpy.sum(1.-kwargs['mask']))/len(kwargs['mask'])
    dof = dof-nparameters-1

    f.write('\n\nResidual chi^2 = {:.0f} for {:.0f} degrees of freedom'.format(stat,dof))
    f.write('\nProbability that model matches data = {:.4f}'.format(stats.chi2.sf(stat,dof)))
    f.write('\nSource/model scale factor = {:.2f} implying a radius of {:.3f} solar radii at 10 pc\n'.format(scl,(scl**0.5*10.*u.pc).to(u.Rsun).value))

    f.write('\n\nFitting completed in {:.1f} seconds = {:.2f} hours'.format(kwargs['total_time'],kwargs['total_time']/3600.))
    f.write('\nResults may be found in the files {}*'.format(kwargs['filebase']))
    f.close()
    return 




#######################################################
#######################################################
#############   ROUNTINES IN DEVELOPMENT  #############  
#######################################################
#######################################################



def calcLuminosity(sp, mdl=False, absmags=False, **kwargs):
    '''
    :Purpose: Calculate luminosity from photometry and stitching models.

    THIS IS CURRENTLY BEING WRITTEN - DO NOT USE!

    :param sp: Spectrum class object, which should contain wave, flux and 
               noise array elements.
    :param mdl: model spectrum loaded using ``loadModel``
    :type mdl: default = False
    :param absmags: a dictionary whose keys are one of the following filters: 'SDSS Z', 
                    '2MASS J', '2MASS H', '2MASS KS', 'MKO J', 'MKO H', 'MKO K', 'SDSS R', 
                    'SDSS I', 'WISE W1', 'WISE W2', 'WISE W3', 'WISE W4', 'IRAC CH1', 
                    'IRAC CH2', 'IRAC CH3', 'IRAC CH4'
    :type absmags: default = False
    
    '''

    spec_filters = ['SDSS Z','2MASS J','2MASS H','2MASS KS','MKO J','MKO H','MKO K']
    sed_filters = ['SDSS R','SDSS I','WISE W1','WISE W2','WISE W3','WISE W4','IRAC CH1','IRAC CH2','IRAC CH3','IRAC CH4']
    
    if ~isinstance(absmags,dict):
        raise ValueError('\nAbsolute magnitudes should be a dictionary whose keys are one of the following filters:\n{}'.format(spec_filters+sed_filters))

# read in a model if one is not provided based on classification and temperature
    if mdl == False or 'SED' not in mdl.name:
        spt,spt_unc = classifyByIndex(sp)
        teff,unc = spemp.typeToTeff(spt)
        mdl = loadModel(teff=teff,logg=5.0,sed=True)

# prep arrays
    flux = []
    flux_unc = []
    flux_wave = []
    
# steps:
# scale spectrum to absolute magnitude if necessary and integrate flux, varying noise and including variance in abs mag factor
    spcopy = sp
    if spcopy.fscale != 'Absolute':
        scale = []
        scale_unc = []
        for k in absmags.keys():
            if k.upper() in spec_filters:
                m = spphot.filterMag(spcopy,k)
                scale.extend(10.**(0.4*(m-absmags[k][0])))
# note: need to add in spectral flux uncertainty as well
                scale_unc.extend(numpy.log(10.)*0.4*absmags[k][1]*scale[-1])
        if len(scale) == 0:
            raise ValueError('\nNo absolute magnitudes provided to scale spectrum; you specified:\n{}'.format(absmags.keys()))
        scl,scl_e = weightedMeanVar(scale,scale_unc,uncertainty=True)
        spcopy.scale(numpy.mean(scl))
        spcopy.fscale = 'Absolute'

# integrate data
# NEED TO INSERT UNCERTAINTY HERE
    flux.extend(trapz(spcopy.flux,spcopy.wave))
    flux_unc.extend(0.)
    flux_wave.extend([numpy.nanmin(spcopy.wave),numpy.nanmax(spcopy.wave)])

# scale segments of models scaled to WISE or IRAC bands if available, include variance in abs mag factor
# PROBLEM: WHAT IF SPECTRAL PIECES OVERLAP?
    for k in absmags.keys():
        if k.upper() in sed_filters:
            filterdat = spphot.filterProperties(k.upper())
            mdl.fluxCalibrate(k,absmags[k][0])
            w = numpy.where(mdl.wave.value >= filterdat['lambda_min'] and mdl.wave.value <= filterdat['lambda_max'])
            flux.extend(trapz(mdl.flux[w],mdl.wave[w]))
            flux_unc.extend(2.5*numpy.log(10.)*absmags[k][1]*flux[-1])
            flux_wave.extend([filterdat['lambda_min'],filterdat['lambda_max']])

# match model between these scaled pieces and out to ends and integrate, include variance in abs mag factor(s)
# report log luminosity in solar units and uncertainty
# optional report the various pieces and percentages of whole ()
#
# absmags is a dictionary whose keys are filter names and whose elements are 2-element lists of value and uncertainty        

    
