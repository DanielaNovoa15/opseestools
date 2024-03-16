# -*- coding: utf-8 -*-
"""
Created on Wed Mar 30 12:50:00 2022

@author: orlandoaram
"""
from openseespy.opensees import *
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import argrelextrema
from scipy.stats import gmean
from scipy.fft import fft, ifft


def MomentCurvature(secTag, axialLoad, maxK, numIncr=300):
    # Script tomado de la librería de OpenSeespy de la web
    # secTag es el tag de la sección
    # axialLoad es la carga axial de la sección
    # maxK es la curvatura
    # numIncr es el número de incrementos
    # Define two nodes at (0,0)
    
    model('basic','-ndm',2,'-ndf',3)
    a = getNodeTags()
    if not a:
        a = [0] # si no hay nodos inicia la lista en cero
    n1 = max(a)+1
    n2 = max(a)+2
    print(n1,n2)
    node(n1, 0.0, 0.0)
    node(n2, 0.0, 0.0)

    # Fix all degrees of freedom except axial and bending
    fix(n1, 1, 1, 1)
    fix(n2, 0, 1, 0)
    
    # Define element
    #                             tag ndI ndJ  secTag
    b = getEleTags()
    if not b:
        b = [0] # si no hay nodos inicia la lista en cero
    e1 = max(b)+1
    element('zeroLengthSection',  e1,   n1,   n2,  secTag)

    # Define constant axial load
    timeSeries('Constant', n1)
    pattern('Plain', n1, n1)
    load(n2, axialLoad, 0.0, 0.0)

    # Define analysis parameters
    wipeAnalysis()
    integrator('LoadControl', 1.0)
    system('SparseGeneral', '-piv')
    test('NormUnbalance', 1e-9, 10)
    numberer('Plain')
    constraints('Plain')
    algorithm('Newton')
    analysis('Static')

    # Do one analysis for constant axial load
    analyze(1)
    loadConst('-time',0.0)

    # Define reference moment
    timeSeries('Linear', n2)
    pattern('Plain',n2, n2)
    load(n2, 0.0, 0.0, 1.0)

    # Compute curvature increment
    dK = maxK / numIncr

    # Use displacement control at node 2 for section analysis
    wipeAnalysis()
    integrator('DisplacementControl', n2,3,dK,1,dK,dK)
    system('SparseGeneral', '-piv')
    test('NormUnbalance', 1e-9, 10)
    numberer('Plain')
    constraints('Plain')
    algorithm('Newton')
    analysis('Static')
    
    M = [0]
    curv = [0]
    
    # Do the section analysis
    for i in range(numIncr):
        analyze(1)
        curv.append(nodeDisp(n2,3))
        M.append(getTime())
    plt.figure()
    plt.plot(curv,M)
    plt.xlabel('Curvatura')
    plt.ylabel('Momento (kN-m)')
    # wipe()
    nodes = [n1,n2]
    return M,curv

def testMaterial(matTag,displ):
    # wipe()
    
    model('basic','-ndm',2,'-ndf',3)
    # h = getNodeTags()

    node(100,0.0,0.0)
    node(200,0.0,0.0)
    
    fix(100,1,1,1)
    fix(200,1,1,0)
    
    controlnode = 200
    element('zeroLength',1,100,200,'-mat',matTag,'-dir',6)
    
    recorder('Node','-file','MPhi.out','-time','-node',2,'-dof',3,'disp')
    recorder('Element','-file','Moment.out','-time','-ele',1,'force')
    
    ratio = 1/1000
    
    timeSeries('Linear',1)
    pattern('Plain',1,1)
    load(200,0.0,0.0,1.0)
    
    constraints('Plain')
    numberer('Plain')
    system('BandGeneral')
    test('EnergyIncr',1e-6,1000)
    algorithm('Newton')
    
    currentDisp = 0.0
    Disp = [0]
    F = [0]
    nSteps = 1000
    
    for i in displ:
        Dincr = ratio*i/nSteps
        integrator('DisplacementControl',controlnode,3,Dincr)
        analysis('Static')
        
        if Dincr > 0:
            Dmax = Dincr*nSteps
            ok = 0
            while ok == 0 and currentDisp < Dmax:
                ok = analyze(1)
                currentDisp = nodeDisp(controlnode,3)
                F.append(getTime())
                Disp.append(currentDisp)
        elif Dincr < 0:
            Dmax = Dincr*nSteps
            ok = 0
            while ok == 0 and currentDisp > Dmax:
                ok = analyze(1)
                currentDisp = nodeDisp(controlnode,3)
                F.append(getTime())
                Disp.append(currentDisp)
    Fcurr = getTime()
    if ok != 0:
        print('Fallo la convergencia en ',Fcurr)
    else:
        print('Analisis completo')
    
    plt.figure()
    plt.plot(Disp,F)
    plt.xlabel('deformación unitaria (m/m)')
    plt.ylabel('esfuerzo (kPa)')
    return Disp,F
    
def BuildRCSection(ID,HSec,BSec,coverH,coverB,coreID,coverID,steelID,numBarsTop,barAreaTop,numBarsBot,barAreaBot,numBarsIntTot,barAreaInt,nfCoreY,nfCoreZ,nfCoverY,nfCoverZ):
    # Define a procedure which generates a rectangular reinforced concrete section
	# with one layer of steel at the top & bottom, skin reinforcement and a 
	# confined core.
	#		by: Silvia Mazzoni, 2006
	#			adapted from Michael H. Scott, 2003
	# 
	# Formal arguments
	#    id - tag for the section that is generated by this procedure
	#    HSec - depth of section, along local-y axis
	#    BSec - width of section, along local-z axis
	#    cH - distance from section boundary to neutral axis of reinforcement
	#    cB - distance from section boundary to side of reinforcement
	#    coreID - material tag for the core patch
	#    coverID - material tag for the cover patches
	#    steelID - material tag for the reinforcing steel
	#    numBarsTop - number of reinforcing bars in the top layer
	#    numBarsBot - number of reinforcing bars in the bottom layer
	#    numBarsIntTot - TOTAL number of reinforcing bars on the intermediate layers, symmetric about z axis and 2 bars per layer-- needs to be an even integer
	#    barAreaTop - cross-sectional area of each reinforcing bar in top layer
	#    barAreaBot - cross-sectional area of each reinforcing bar in bottom layer
	#    barAreaInt - cross-sectional area of each reinforcing bar in intermediate layer 
	#    nfCoreY - number of fibers in the core patch in the y direction
	#    nfCoreZ - number of fibers in the core patch in the z direction
	#    nfCoverY - number of fibers in the cover patches with long sides in the y direction
	#    nfCoverZ - number of fibers in the cover patches with long sides in the z direction
    
    coverY = HSec/2.0
    coverZ = BSec/2.0
    coreY = coverY - coverH
    coreZ = coverZ - coverB
    numBarsInt = int(numBarsIntTot/2)
    GJ = 1e6
    nespacios = numBarsInt + 1
    a = HSec - 2*coverH
    b = a/nespacios
        
    section('Fiber',ID,'-GJ',GJ)
    patch('quad',coreID,nfCoreZ,nfCoreY,-coreY,coreZ,-coreY,-coreZ,coreY,-coreZ,coreY,coreZ)
    patch('quad',coverID,2,nfCoverY,-coverY,coverZ,-coreY,coreZ,coreY,coreZ,coverY,coverZ)
    patch('quad',coverID,2,nfCoverY,-coreY,-coreZ,-coverY,-coverZ,coverY,-coverZ,coreY,-coreZ)
    patch('quad',coverID,nfCoverZ,2,-coverY,coverZ,-coverY,-coverZ,-coreY,-coreZ,-coreY,coreZ)
    patch('quad',coverID,nfCoverZ,2,coreY,coreZ,coreY,-coreZ,coverY,-coverZ,coverY,coverZ)    
    layer('straight',steelID,numBarsInt,barAreaInt,-coreY+b,coreZ,coreY-b,coreZ) # este
    layer('straight',steelID,numBarsInt,barAreaInt,-coreY+b,-coreZ,coreY-b,-coreZ) # y este
    layer('straight',steelID,numBarsTop,barAreaTop,coreY,coreZ,coreY,-coreZ)
    layer('straight',steelID,numBarsBot,barAreaBot,-coreY,coreZ,-coreY,-coreZ)
    
    
        

def e20Lobatto2(Gfc,Lel,npint,fc,E,e0):
    
    # TODO TIENE QUE ESTAR EN UNIDADES DE N y mm
    # Gfc entra en N/mm: Energía de fractura
    # Lel es la longitud del elemento en mm
    # npint es el número de puntos de integración
    # fc es el esfuerzo a compresión del concreto en N/mm2 (MPa)
    # E es el módulo de elasticidad del concreto en N/mm2 (MPa)
    # e0 es la deformación del concreto en fc
    
    if npint == 4:
        LIP = Lel/2*1/6
    elif npint == 5:
        LIP = Lel/2*1/10
    elif npint == 6:
        LIP = Lel/2*1/15
    elif npint == 3:
        LIP = Lel/2*1/3
    else:
        LIP = 0.1*Lel
        print('numero de puntos no soportado')
    
    e20 = Gfc/(0.6*fc*LIP)-0.8*fc/E+e0
    
    return e20


def nse(pred,obs):
    # calcula el índice normalizado de Nash-Sutcliffe
    # pred es la predicción numérica
    # obs es el ensayo
    mean = np.mean(obs)
    denom = np.sum((obs-mean)**2)
    nume = np.sum((obs-pred)**2)
    ns1 = 1-(nume/denom)
    ns = 1/(2-ns1)
    return ns


def kge(pred,obs):
    # calcula el índice de Kling Gupta
    # pred es la predicción numérica
    # obs es el ensayo
    r = np.corrcoef(pred,obs)[0,1]
    ssim = np.std(pred)
    sobs = np.std(obs)
    msim = np.mean(pred)
    mobs = np.mean(obs)
    cr = r-1
    cs = ssim/sobs - 1
    cm = msim/mobs - 1
    kge = 1-np.sqrt(cr**2 + cs**2 + cm**2)
    return kge


def newmarkL(T,xi,GM,delta_t,betha = 1/6, gamma = 1/2 ,u0 = 0,v0 = 0,P0 = 0):
    #T: periodo de la estrutura
    #xi: porcentaje de amortiguamiento crítico
    #GM: registro en unidades consistentes
    #delta_t: delta de tiempo del registro
    #betha, gamma: parámetros del Newmark. Por defecto utiliza método lineal de interpolación
    #u0,v0,a0: condiciones iniciales de desplazamiento velocidad y aceleración
    
    w = 2*np.pi/T
    m = 1.0
    k = m*w**2
    c = 2*xi*m*w
    # Calculos iniciales
    a0 = (P0-c*v0-k*u0)/m                     # Aceleración inicial
    a1 = m/(betha*(delta_t**2))+(gamma*c)/(betha*delta_t)
    a2 = m/(betha*delta_t)+(gamma/betha-1)*c
    a3 = (1/(2*betha)-1)*m+delta_t*(gamma/(2*betha)-1)*c
    k_g = k+a1
    
    # INICIAR VARIABLES
    
    Npts = len(GM)+1
    Desplz = np.zeros((Npts,1))
    Vel = np.zeros((Npts,1))
    Acel = np.zeros((Npts,1))
    Tiempo = np.linspace(0,delta_t*(Npts-1),Npts)
    P_1 = GM*m
    P_2 = np.zeros((Npts,1))
    
    for i in range(Npts-1):
        P_2[i+1] = P_1[i] + a1*Desplz[i] + a2*Vel[i] + a3*Acel[i]
        Desplz[i+1] = P_2[i+1]/k_g
        Vel[i+1] = gamma/(betha*delta_t)*(Desplz[i+1]-Desplz[i])+(1-(gamma/betha))*Vel[i]+delta_t*(1-(gamma/(2*betha)))*Acel[i]
        Acel[i+1] = (Desplz[i+1]-Desplz[i])/(betha*(delta_t**2))-Vel[i]/(betha*delta_t)-(1/(2*betha)-1)*Acel[i]
        
    return Tiempo,Desplz,Vel,Acel


def newmarkLA(T,xi,GM,delta_t,flag = 'all',betha = 1/6, gamma = 1/2 ,u0 = 0,v0 = 0,P0 = 0):
    #T: periodo de la estrutura
    #xi: porcentaje de amortiguamiento crítico
    #GM: registro en unidades consistentes
    #delta_t: delta de tiempo del registro
    #flag: recibe 'max' cuando solo se deseen los valores máximos de tiempo, desplazamiento, velocidad y aceleracion absolutas.
    #betha, gamma: parámetros del Newmark. Por defecto utiliza método lineal de interpolación
    #u0,v0,a0: condiciones iniciales de desplazamiento velocidad y aceleración
    
    
    w = 2*np.pi/T
    m = 1.0
    k = m*w**2
    c = 2*xi*m*w
    # Calculos iniciales
    a0 = (P0-c*v0-k*u0)/m                     # Aceleración inicial
    a1 = m/(betha*(delta_t**2))+(gamma*c)/(betha*delta_t)
    a2 = m/(betha*delta_t)+(gamma/betha-1)*c
    a3 = (1/(2*betha)-1)*m+delta_t*(gamma/(2*betha)-1)*c
    k_g = k+a1
    
    # INICIAR VARIABLES
    
    Npts = len(GM)
    Desplz = np.zeros((Npts))
    Vel = np.zeros((Npts))
    Acel = np.zeros((Npts))
    Tiempo = np.linspace(0,delta_t*(Npts-1),Npts)
    P_1 = GM*m
    P_2 = np.zeros((Npts))
    
    for i in range(Npts-2):
        P_2[i+1] = P_1[i] + a1*Desplz[i] + a2*Vel[i] + a3*Acel[i]
        Desplz[i+1] = P_2[i+1]/k_g
        Vel[i+1] = gamma/(betha*delta_t)*(Desplz[i+1]-Desplz[i])+(1-(gamma/betha))*Vel[i]+delta_t*(1-(gamma/(2*betha)))*Acel[i]
        Acel[i+1] = (Desplz[i+1]-Desplz[i])/(betha*(delta_t**2))-Vel[i]/(betha*delta_t)-(1/(2*betha)-1)*Acel[i]
    
    AcelAbs = Acel + GM # Aquí se calcula la aceleración absoluta
    
    if flag == 'max':
        TT = np.max(np.abs(Tiempo))
        DD = np.max(np.abs(Desplz))
        VV = np.max(np.abs(Vel))
        AA = np.max(np.abs(AcelAbs))
    else:
        TT = Tiempo
        DD = Desplz
        VV = Vel
        AA = Acel
    
    return TT,DD,VV,AA

def spectrum2(GM,delta_t,xi):
    N = 400
    T = np.linspace(0.02,3,N)
    Sa = np.zeros(N)
    U = np.zeros(N)
    V = np.zeros(N)
    
    for i,per in enumerate(T):
        w = 2*np.pi/per
        Tiempo,Desplz,Vel,Acel = newmarkLA(per,xi,GM,delta_t,'max')
        U[i] = Desplz
        V[i] = Vel
        Sa[i] = Desplz*w**2
    return T,Sa


def spectrum4(GM,dt,xi=0.05,rango=[0.02,3.0],N=100):
    ''' está basado en la rutina de OpenSees
        GM: el registro en .txt. Por ejemplo 'GM01.txt'
        dt: dt del registro
        xi: porcentaje del amortiguamiento crítico
        rango: rango de periodos en un vector
        N: número de puntos
           
    '''
    m = 1
    T = np.linspace(rango[0],rango[1],N)
    w = 2*np.pi/T
    k = m*w**2
    c = 2*xi*m*w
    Sa = np.zeros(N)
    U = np.zeros(N)
    A = np.zeros(N)
    dmax,amax = [],[]
    for indx, frec in enumerate(w):
        umax,ufin,uperm,amax,tamax = sdfResponse(m,xi,k[indx],1e16,0.05,dt,GM,dt)
        U[indx] = umax
        Sa[indx] = umax*frec**2
        A[indx] = amax
    return T,Sa,U,A

# def espectroNSR(Aa,Av,Fa,Fv,I):
#     T = np.linspace(0,4,500)
#     T0 = 0.1*(Av*Fv)/(Aa*Fa)
#     Tc = 0.48*(Av*Fv)/(Aa*Fa)
#     Tl = 2.4*Fv
#     Sa = (T < T0)*2.5*Aa*Fa*I*(0.4+0.6*T/T0) + ((T0 < T) & (T < Tc))*2.5*Aa*Fa*I + ((Tc < T) & (T < Tl))*1.2*Av*Fv*I/T + (Tl < T)*1.2*Av*Fv*I*Tl/T**2
#     return T,Sa

# T,Sa = espectroNSR(0.15, 0.2, 2.1, 3.2, 1.0)

# plt.plot(T,Sa)

def plot_Wall_T_BE(matConf, matInco, bW, bF, BEU, BED, BEL, BER, Lww, LwF, nMax, nMin):
    
    cover = 0.025
    SteelTag = 4
    
    fib_sec_1 = [['section', 'Fiber', 2, '-GJ', 1e16],
         ['patch','rect',matInco, nMax, nMin, -Lww/2, -bW/2, Lww/2, bW/2], 
         ['patch','rect',matConf, int(nMax/3), nMin, Lww/2, -bW/2, Lww/2+BEU, bW/2],
         ['patch','rect',matConf, int(nMax/3), nMin, -Lww/2-BED, -bW/2, -Lww/2, bW/2],
         # ['patch','rect',matInco, nMin, int(nMax/3), Lww/2+BEU-bF, -bW/2-LwF, Lww/2+BEU, -bW/2],
         # ['patch','rect',matInco, nMin, int(nMax/3), Lww/2+BEU-bF, bW/2, Lww/2+BEU, bW/2+LwF],
         # ['patch','rect',matConf, nMin, int(nMax/3), Lww/2+BEU-bF, bW/2+LwF, Lww/2+BEU, bW/2+LwF+BEL],
         # ['patch','rect',matConf, nMin, int(nMax/3), Lww/2+BEU-bF, -bW/2-LwF-BER, Lww/2+BEU, -bW/2-LwF],
         ['layer','straight',SteelTag,3,area_bar4,2.48,-0.075+cover,2.025+cover,-0.075+cover],    ####Refuerzo en el alma confinamientos
         ['layer','straight',SteelTag,3,area_bar4,2.48,0.075-cover,2.025+cover,0.075-cover],
         ['layer','straight',SteelTag,3,area_bar4,-2.48,-0.075+cover,-2.025-cover,-0.075+cover],
         ['layer','straight',SteelTag,3,area_bar4,-2.48,0.075-cover,-2.025-cover,0.075-cover],
         
         ['layer','straight',SteelTag,27,area_malla7,-2+cover,-0.075+cover,2.0-cover,-0.075+cover],
         ['layer','straight',SteelTag,27,area_malla7,-2+cover,0.075-cover,2.0-cover,0.075-cover],
         
         # ['layer','straight',SteelTag,3,area_bar4,2.5-cover,-2.5+cover,2.5-cover,-2.5-cover+BEf],  #####Refurezo en patin confinamientos
         # ['layer','straight',SteelTag,3,area_bar4,2.35+cover,-2.5+cover,2.35+cover,-2.5-cover+BEf],
         # ['layer','straight',SteelTag,3,area_bar4,2.5-cover,2.5-cover,2.5-cover,2.5+cover-BEf],
         # ['layer','straight',SteelTag,3,area_bar4,2.35+cover,2.5-cover,2.35+cover,2.5+cover-BEf],
         
         ['layer','straight',SteelTag,13,area_malla7,2.475-cover,-2.50+cover+BEf,2.475-cover,-2.50-cover+BEf+Flange],  #superior
         ['layer','straight',SteelTag,13,area_malla7,2.375+cover,-2.50+cover+BEf,2.375+cover,-2.50-cover+BEf+Flange],    #inferior
         ['layer','straight',SteelTag,13,area_malla7,2.475-cover,2.50-cover-BEf,2.475-cover,2.50+cover-BEf-Flange],    #superior
         ['layer','straight',SteelTag,13,area_malla7,2.375+cover,2.50-cover-BEf,2.375+cover,2.50+cover-BEf-Flange]]      #inferior
 
    # plt.gca().invert_xaxis()
   
    return fib_sec_1
  
    matcolor = ['r', 'lightgrey', 'gold', 'w', 'w', 'w']
    opsv.plot_fiber_section(fib_sec_1, matcolor=matcolor)
    plt.axis('equal')
    plt.axhline(y=0, color='r', lw = 0.5)
    plt.axvline(x=0, color='r', lw = 0.5)
    # plt.ylim(0,14)
    # plt.xlim(-6,6)
    plt.gca().invert_xaxis()
    
def dackal(Fyy, Fuu, eyy, ehh, euu, Lb, Db):
    #Fy = esfuerzo de fluencia del acero [MPa]
    #Fu = esfuerzo último del acero [MPa]
    #ey, eh, eu = deformaciones unitarias del acero
    #L = Espaciamiento entre estribos (Longitud libre para pandearse) [mm]
    #D = Diámetro de la barra [mm]
    fy = Fyy
    fu = Fuu
    fh = fy+0.01
    ey = eyy
    eu = euu
    eh = ehh
    L = Lb
    D = Db
    alfa = 0.75
    efracture = 0.05
    espalling = 0.004
    sigma_u = 0.2*fy
    p1 = [eh,eu]
    p2 = [fh,fu]
    Es = fy/ey
    m = -0.02*Es
    eas = np.max([(55-2.3*np.sqrt(fy/100)*L/D)*ey,7*ey])
    sigma_l = np.interp(eas,p1,p2)
    sigma_as = np.max([alfa*(1.1-0.016*np.sqrt(fy/100)*L/D)*sigma_l,0.2*fy])
    eu_d = (sigma_u-sigma_as)/m + eas
    sigma_f = np.interp(efracture,p1,p2)
    sigma_s = np.interp(espalling,p1,p2)
    # strain = [-eu_d,-espalling,-ey,0.0,ey,efracture,eu]
    # stress = [-sigma_u,-sigma_s,-fy,0.0, fy,sigma_f, sigma_u]
    strain = [-eu_d,-eas,-espalling,-ey,0.0,ey,eh,efracture,eu]
    stress = [-sigma_u,-sigma_as,-sigma_s,-fy,0.0, fy,fh,sigma_f, sigma_u]

    s = [fy*1000,fh*1000,sigma_f*1000, sigma_u*1000,-fy*1000,-sigma_s*1000,-sigma_as*1000,-sigma_u*1000]
    e = [ey,eh,efracture,eu,-ey,-espalling,-eas,-eu_d]
 
    
    return s, e

def residual_disp(drifts,npts):
    ''' Calcula el drift residual de una estructura sometida a un terremoto
        Recibe dos entradas:
            drifts contiene los drifts a lo largo del sismo
            npts es el número de puntos hasta donde llega el registro
        
        Este algoritmo requiere que se haya corrido un periodo de vibración libre luego del final del registro
        
    '''
    freevib = drifts[npts:-1] # extrae los valores de drifts a partir de donde comenzó la vibración libre
    peaks_ind = argrelextrema(freevib, np.greater) # calcula los indices de los puntos de los máximos
    peaks_ind = peaks_ind[0]
    valleys_ind = argrelextrema(freevib, np.less) # calcula los indices de los puntos de los mínimos
    valleys_ind = valleys_ind[0]
    drifts1 = np.abs(freevib[peaks_ind]) # identifica los drifts de los picos
    drifts2 = np.abs(freevib[valleys_ind]) # identifica los drifts de los valles
    resdrift = np.mean(np.concatenate((drifts1,drifts2))) # promedia los drifts de picos y valles
    return resdrift
                       
def Sa_avg(T,Sa,T2 = np.linspace(0.02,3,299)):
    sa_avg = np.zeros(len(T2))
    # sa_avg2 = np.zeros(len(T2)) # en casi que queramos definir con media aritmetica
    for ind,tt in enumerate(T2):
        ta = 0.2*tt # entre 0.2T
        tb = 2.5*tt # y 2.5T
        periods = np.linspace(ta,tb,int(np.ceil((tb-ta)/0.01))) # intervalos de 0.1
        Sas2 = np.interp(periods,T,Sa)
        sa_avg[ind] = gmean(Sas2)
        # sa_avg2[ind] = np.mean(Sas2) # definir con media aritmetica
    return T2,sa_avg


def EAF(t,a):
    '''Función para construir el espectro de amplitud de fourier
    t es el tiempo del registro
    a es el registro (acelerograma)
    '''
    N = len(a)
    td = t[-1]
    # dt = td/N
    dw = 2*np.pi/td
    Nf = int(N/2 + 1)
    NT = np.linspace(0,Nf-1,Nf)
    W = NT*dw
    
    TF = fft(a)/N*td
    TF1 = TF[0:Nf]
    A = np.zeros(Nf)
    for i in range(Nf):
        A[i] = np.linalg.norm(TF1[i])
    
    T = 2*np.pi*np.reciprocal(W[1::])
    # F = W/(2*np.pi)
    return T,A[1::]