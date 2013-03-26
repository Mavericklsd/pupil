from ctypes import c_int,c_bool,c_float
import cPickle as pickle
import numpy as np
import atb
from glfw import *
from gl_utils import adjust_gl_view, draw_gl_texture, clear_gl_screen,draw_gl_point,draw_gl_point_norm,draw_gl_polyline
from time import time, sleep
from methods import *
from calibrate import *
from methods import Temp,capture,make_eye_kernel
from os import path

class Bar(atb.Bar):
    """docstring for Bar"""
    def __init__(self, name,g_pool, bar_defs):
        super(Bar, self).__init__(name,**bar_defs)
        self.fps = c_float(0.0)
        self.timestamp = time()
        self.dt = c_float(0.0)
        self.sleep = c_float(0.0)
        self.display = c_int(1)
        self.draw_pupil = c_bool(1)
        self.draw_roi = c_int(0)
        self.bin_thresh = c_int(60)
        self.blur = c_int(3)
        self.pupil_ratio = c_float(.6)
        self.pupil_angle = c_float(0.0)
        self.pupil_size = c_float(80.)
        self.pupil_size_tolerance = c_float(40.)
        self.canny_aperture = c_int(7)
        self.canny_thresh = c_int(200)
        self.canny_ratio = c_int(2)
        self.record_eye = c_bool(0)

        #add class field here and it will become session persistant
        self.session_save = {'display':self.display,
                            'draw_pupil':self.draw_pupil,
                            'bin_thresh':self.bin_thresh,
                            'pupil_ratio':self.pupil_ratio,
                            'pupil_size':self.pupil_size,
                            'mean_blur':self.blur,
                            'canny_aperture':self.canny_aperture,
                            'canny_thresh':self.canny_thresh,
                            'canny_ratio':self.canny_ratio}

        self.load()

        self.add_var("Display/FPS",self.fps, step=1.,readonly=True)
        self.add_var("Display/SlowDown",self.sleep, step=0.01,min=0.0)
        self.add_var("Display/Mode", self.display, step=1,max=3, min=0, help="select the view-mode")
        self.add_var("Display/Show_Pupil_Point", self.draw_pupil)
        self.add_button("Draw_ROI", self.roi, help="drag on screen to select a region of interest", Group="Display")
        self.add_var("Darkspot/Threshold", self.bin_thresh, step=1, max=256, min=0)
        self.add_var("Pupil/Ratio", self.pupil_ratio, step=.05, max=1., min=0.)
        # self.add_var("Pupil/Angle", self.pupil_angle,step=1.0,readonly=True)
        self.add_var("Pupil/Size", self.pupil_size, step=1, min=0)
        self.add_var("Pupil/Size_Tolerance", self.pupil_size_tolerance, step=1, min=0)
        self.add_var("Canny/MeanBlur", self.blur,step=2,max=7,min=1)
        self.add_var("Canny/Aperture",self.canny_aperture, step=2, max=7, min=3)
        self.add_var("Canny/Lower_Threshold", self.canny_thresh, step=1,min=1)
        self.add_var("Canny/LowerUpperRatio", self.canny_ratio, step=1,min=0,help="Canny recommended a ratio between 3/1 and 2/1")
        self.add_var("record_eye_video", self.record_eye, help="when recording also save the eye video stream")
        self.add_var("SaveSettings&Exit", g_pool.quit)

    def update_fps(self):
        old_time, self.timestamp = self.timestamp, time()
        dt = self.timestamp - old_time
        if dt:
            self.fps.value += .05 * (1 / dt - self.fps.value)
        self.dt = dt

    def save(self):
        new_settings = dict([(key,field.value) for key, field in self.session_save.items()])
        settings_file = open('session_settings','wb')
        pickle.dump(new_settings,settings_file)
        settings_file.close

    def roi(self):
        self.draw_roi.value = 2


    def load(self):
        try:
            settings_file = open('session_settings','rb')
            new_settings = pickle.load(settings_file)
            settings_file.close
        except IOError:
            print "No session_settings file found. Using defaults"
            return

        for key,val in new_settings.items():
            try:
                self.session_save[key].value = val
            except KeyError:
                print "Warning the Sessions file is from a different version, not all fields may be updated"


class Roi(object):
    """this is a simple 2D Region of Interest class
    it is applied on numpy arrays for convinient slicing
    like this:

    roi_array_slice = full_array[r.lY:r.uY,r.lX:r.uX]
    #do something with roi_array_slice
    full_array[r.lY:r.uY,r.lX:r.uX] = roi_array_slice

    this creates a view, no data copying done
    """
    def __init__(self, array_shape):
        self.array_shape = array_shape
        self.lX = 0
        self.lY = 0
        self.uX = array_shape[1]-0
        self.uY = array_shape[0]-0
        self.nX = 0
        self.nY = 0
        self.load()

    def setStart(self,(x,y)):
        x,y = max(0,x),max(0,y)
        self.nX,self.nY = x,y

    def setEnd(self,(x,y)):
            x,y = max(0,x),max(0,y)
            #make sure the ROI actually contains pixels
            if abs(self.nX - x) > 2 and abs(self.nY - y)>2:
                self.lX = min(x,self.nX)
                self.lY = min(y,self.nY)
                self.uX = max(x,self.nX)
                self.uY = max(y,self.nY)

    def add_vector(self,(x,y)):
        """
        adds the roi offset to a len2 vector
        """
        return (self.lX+x,self.lY+y)

    def set(self,vals):
        if vals is not None and len(vals) is 4:
            self.lX,self.lY,self.uX,self.uY = vals

    def get(self):
        return self.lX,self.lY,self.uX,self.uY

    def save(self):
        new_settings = Temp()
        new_settings.array_shape = self.array_shape
        new_settings.vals = self.get()
        settings_file = open('session_settings_roi','wb')
        pickle.dump(new_settings,settings_file)
        settings_file.close

    def load(self):
            try:
                settings_file = open('session_settings_roi','rb')
                new_settings = pickle.load(settings_file)
                settings_file.close
            except IOError:
                print "No session_settings_roi file found. Using defaults"
                return

            if new_settings.array_shape == self.array_shape:
                self.set(new_settings.vals)
            else:
                print "Warning: Image Array size changed, disregarding saved Region of Interest"

def eye_profiled(src,size,g_pool):
    import cProfile
    from eye import eye
    cProfile.runctx("eye(src,size,g_pool)",{'src':src,"size":size,"g_pool":g_pool},locals(),"eye.pstats")

def eye(src,size,g_pool):
    """
    this process needs a docstring
    """
    # # callback functions
    def on_resize(w, h):
        atb.TwWindowSize(w, h);
        adjust_gl_view(w,h)

    def on_key(key, pressed):
        if not atb.TwEventKeyboardGLFW(key,pressed):
            if pressed:
                if key == GLFW_KEY_ESC:
                    on_close()

    def on_char(char, pressed):
        if not atb.TwEventCharGLFW(char,pressed):
            pass

    def on_button(button, pressed):
        if not atb.TwEventMouseButtonGLFW(button,pressed):
            if bar.draw_roi.value:
                if pressed:
                    pos = glfwGetMousePos()
                    pos = normalize(pos,glfwGetWindowSize())
                    pos = denormalize(pos,(img.shape[1],img.shape[0]) ) #pos in img pixels
                    r.setStart(pos)
                    bar.draw_roi.value = 1
                else:
                    bar.draw_roi.value = 0

    def on_pos(x, y):
        if atb.TwMouseMotion(x,y):
            bar.update()
        if bar.draw_roi.value == 1:
            pos = glfwGetMousePos()
            pos = normalize(pos,glfwGetWindowSize())
            pos = denormalize(pos,(img.shape[1],img.shape[0]) ) #pos in img pixels
            r.setEnd(pos)

    def on_scroll(pos):
        if not atb.TwMouseWheel(pos):
            pass

    def on_close():
        g_pool.quit.value = True
        print "EYE Process closing from window"

    # initialize capture, check if it works
    cap = capture(src, size)
    s, img = cap.read_RGB()
    if not s:
        print "EYE: Error could not get image"
        return
    height,width = img.shape[:2]

    cap.auto_rewind = True

    # pupil object
    pupil = Temp()
    pupil.norm_coords = (0.,0.)
    pupil.image_coords = (0.,0.)
    pupil.ellipse = None
    pupil.gaze_coords = (0.,0.)
    try:
        pupil.pt_cloud = list(np.load('cal_pt_cloud.npy'))  #LIST just makes it conform with \
                                                            #how our pupil data is captured during calibration
    except:
        pupil.pt_cloud = None
    if pupil.pt_cloud is not None:
        pupil.coefs = calibrate_poly(pupil.pt_cloud)
    else:
        pupil.coefs = None

    r = Roi(img.shape)
    p_r = Roi(img.shape)


    # local object
    l_pool = Temp()
    l_pool.calib_running = False
    l_pool.record_running = False
    l_pool.record_positions = []
    l_pool.record_path = None
    l_pool.writer = None
    l_pool.region_r = 20

    atb.init()
    bar = Bar("Eye",g_pool, dict(label="Controls",
            help="Scene controls", color=(50,50,50), alpha=50,
            text='light', refresh=.2, position=(10, 10), size=(200, 300)) )

    #add 4vl2 camera controls to ATB bar
    import v4l2_ctl
    controls = v4l2_ctl.extract_controls(src)
    bar.camera_ctl = dict()
    bar.camera_state = dict()
    for control in controls:
        if control["type"]=="(bool)":
            bar.camera_ctl[control["name"]]=c_bool(control["value"])
            bar.camera_state[control["name"]]=c_bool(control["value"])
            bar.add_var("Camera/"+control["name"],bar.camera_ctl[control["name"]])
        elif control["type"]=="(int)":
            bar.camera_ctl[control["name"]]=c_int64(control["value"])
            bar.camera_state[control["name"]]=c_int64(control["value"])
            bar.add_var("Camera/"+control["name"],bar.camera_ctl[control["name"]],max=control["max"],min=control["min"],step=control["step"])
        elif control["type"]=="(menu)":
            bar.camera_ctl[control["name"]]=c_int64(control["value"])
            bar.camera_state[control["name"]]=c_int64(control["value"])
            bar.add_var("Camera/"+control["name"],bar.camera_ctl[control["name"]],max=control["max"],min=control["min"],step=1)
        else:
            pass


    # Initialize glfw
    glfwInit()
    glfwOpenWindow(width, height, 0, 0, 0, 8, 0, 0, GLFW_WINDOW)
    glfwSetWindowTitle("Eye")
    glfwSetWindowPos(800,0)
    if isinstance(src, str):
        glfwSwapInterval(0) # turn of v-sync when using video as src for benchmarking


    #register callbacks
    glfwSetWindowSizeCallback(on_resize)
    glfwSetWindowCloseCallback(on_close)
    glfwSetKeyCallback(on_key)
    glfwSetCharCallback(on_char)
    glfwSetMouseButtonCallback(on_button)
    glfwSetMousePosCallback(on_pos)
    glfwSetMouseWheelCallback(on_scroll)

    #gl_state settings
    import OpenGL.GL as gl
    gl.glEnable(gl.GL_POINT_SMOOTH)
    gl.glPointSize(20)
    gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
    gl.glEnable(gl.GL_BLEND)
    del gl


    #event loop
    while glfwGetWindowParam(GLFW_OPENED) and not g_pool.quit.value:
        bar.update_fps()
        s,img = cap.read_RGB()
        sleep(bar.sleep.value) # for debugging only

        #update camera control if needed
        for k in bar.camera_ctl.viewkeys():
            if bar.camera_state[k].value != bar.camera_ctl[k].value:
                print k, ":", bar.camera_ctl[k].value
                v4l2_ctl.set(src,k,bar.camera_ctl[k].value)
                bar.camera_state[k].value= bar.camera_ctl[k].value

        ###IMAGE PROCESSING
        gray_img = grayscale(img[r.lY:r.uY,r.lX:r.uX])

        # integral = cv2.integral(gray_img)

        ###2D filter response as first estimation of pupil position for automated ROI creation
        downscale = 8
        best_m = 0
        region_r = min(max(9,l_pool.region_r),61)
        lable = 0
        for s in (region_r-1,region_r,region_r+1):
            #simple best of three optimization
            kernel = make_eye_kernel(s,int(3*s))
            g_img = cv2.filter2D(gray_img[::downscale,::downscale],cv2.CV_32F,kernel,borderType=cv2.BORDER_REPLICATE)
            m = np.amax(g_img)
            # print s,m
            x,y = np.where(g_img == m)
            x,y = downscale*y[0],downscale*x[0]
            # cv2.putText(gray_img, str(s)+"-"+str(m), (x,y+lable), cv2.FONT_HERSHEY_SIMPLEX, .35,(255,255,255))
            lable+=40
            inner_r = (s*downscale)/2
            outer_r = int(s*downscale*1.)
            if m > best_m:
                best_m = m
                l_pool.region_r = s
                vals = [max(0,v) for v in (x-outer_r,y-outer_r,x+outer_r,y+outer_r)]
                p_r.set(vals)


        # create view into the gray_img with the bounds of the rough pupil estimation
        pupil_img = gray_img[p_r.lY:p_r.uY,p_r.lX:p_r.uX]


        # pupil_img = cv2.morphologyEx(pupil_img, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT,(5,5)),iterations=2)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7,7))
        binary_img = bin_thresholding(pupil_img,image_upper=bar.bin_thresh.value)
        cv2.dilate(binary_img, kernel,binary_img, iterations=3)
        spec_mask = bin_thresholding(pupil_img, image_upper=250)
        cv2.erode(spec_mask, kernel,spec_mask, iterations=1)

        if bar.blur.value >1:
            pupil_img = cv2.medianBlur(pupil_img,bar.blur.value)


        # create contours using Canny edge dectetion
        contours = cv2.Canny(pupil_img,bar.canny_thresh.value,
                            bar.canny_thresh.value*bar.canny_ratio.value,
                            apertureSize= bar.canny_aperture.value)
        # remove contours in areas not dark enough and where the glint (specteal refelction from IR leds) is
        contours = cv2.min(contours, spec_mask)
        contours = cv2.min(contours,binary_img)


        # Ellipse fitting from countours
        result = fit_ellipse_convexity_check(img[r.lY:r.uY,r.lX:r.uX][p_r.lY:p_r.uY,p_r.lX:p_r.uX],
                            contours,
                            binary_img,
                            ratio=bar.pupil_ratio.value,
                            target_size=bar.pupil_size.value,
                            size_tolerance=bar.pupil_size_tolerance.value)



        # # Vizualizations
        overlay =cv2.cvtColor(pupil_img, cv2.COLOR_GRAY2RGB) #create an RGB view onto the gray pupil ROI
        overlay[:,:,0] = cv2.max(pupil_img,contours) #green channel
        overlay[:,:,2] = cv2.max(pupil_img,binary_img) #blue channel
        overlay[:,:,1] = cv2.min(pupil_img,spec_mask) #red channel


        #draw a blue dotted frame around the automatic pupil ROI in overlay...
        overlay[::2,0] = 0,0,255
        overlay[::2,-1]= 0,0,255
        overlay[0,::2] = 0,0,255
        overlay[-1,::2]= 0,0,255

        # and a solid (white) frame around the user defined ROI
        gray_img[:,0] = 255
        gray_img[:,-1]= 255
        gray_img[0,:] = 255
        gray_img[-1,:]= 255


        if bar.display.value == 0:
            img = img
        elif bar.display.value == 1:
            img[r.lY:r.uY,r.lX:r.uX] = cv2.cvtColor(gray_img, cv2.COLOR_GRAY2RGB)
        elif bar.display.value == 2:
            img[r.lY:r.uY,r.lX:r.uX] = cv2.cvtColor(gray_img, cv2.COLOR_GRAY2RGB)
            img[r.lY:r.uY,r.lX:r.uX][p_r.lY:p_r.uY,p_r.lX:p_r.uX] = overlay
        elif bar.display.value == 3:
            img = cv2.cvtColor(pupil_img, cv2.COLOR_GRAY2RGB)
        else:
            pass

        if result is not None:
            pupil.ellipse, others = result
            pupil.image_coords = r.add_vector(p_r.add_vector(pupil.ellipse['center']))
            #update pupil size,angle and ratio for the ellipse filter algorithm
            bar.pupil_size.value  = bar.pupil_size.value +  .5*(pupil.ellipse['major']-bar.pupil_size.value)
            bar.pupil_ratio.value = bar.pupil_ratio.value + .7*(pupil.ellipse['ratio']-bar.pupil_ratio.value)
            bar.pupil_angle.value = bar.pupil_angle.value + 1.*(pupil.ellipse['angle']-bar.pupil_angle.value)

            # if pupil found tighten the size tolerance
            bar.pupil_size_tolerance.value -=1
            bar.pupil_size_tolerance.value =max(10,min(50,bar.pupil_size_tolerance.value))

            # clamp pupil size
            bar.pupil_size.value = max(60,min(300,bar.pupil_size.value))

            # clamp pupil ratio
            bar.pupil_ratio.value = max(.5,bar.pupil_ratio.value)

            # normalize
            pupil.norm_coords = normalize(pupil.image_coords, (img.shape[1], img.shape[0]),flip_y=True )

            # from pupil to gaze
            pupil.gaze_coords = map_vector(pupil.norm_coords, pupil.coefs)
            g_pool.gaze_x.value, g_pool.gaze_y.value = pupil.gaze_coords

        else:
            pupil.ellipse = None
            g_pool.gaze_x.value, g_pool.gaze_y.value = 0.,0.
            pupil.gaze_coords = None, None #whithout this line the last know pupil position is recorded if none is found

            bar.pupil_size_tolerance.value +=1


        ###CALIBRATION and MAPPING###
        # Initialize Calibration (setup variables and lists)
        if g_pool.calibrate.value and not l_pool.calib_running:
            l_pool.calib_running = True
            pupil.pt_cloud = []
            pupil.coefs = None

        # While Calibrating...
        if l_pool.calib_running and ((g_pool.pattern_x.value != 0) or (g_pool.pattern_y.value != 0)) and pupil.ellipse:
            pupil.pt_cloud.append([pupil.norm_coords[0],pupil.norm_coords[1],
                                g_pool.pattern_x.value, g_pool.pattern_y.value])

        # Calculate mapping coefs
        if not g_pool.calibrate.value and l_pool.calib_running:
            l_pool.calib_running = 0
            if pupil.pt_cloud: # some data was actually collected
                pupil.coefs = calibrate_poly(pupil.pt_cloud)
                np.save('cal_pt_cloud.npy', np.array(pupil.pt_cloud))


        ###RECORDING###
        # Setup variables and lists for recording
        if g_pool.pos_record.value and not l_pool.record_running:
            l_pool.record_path = g_pool.eye_rx.recv()
            print "l_pool.record_path: ", l_pool.record_path

            video_path = path.join(l_pool.record_path, "eye.avi")
            #FFV1 -- good speed lossless big file
            #DIVX -- good speed good compression medium file
            if bar.record_eye.value:
                l_pool.writer = cv2.VideoWriter(video_path, cv2.cv.CV_FOURCC(*'DIVX'), bar.fps.value, (img.shape[1], img.shape[0]))
            l_pool.record_positions = []
            l_pool.record_running = True

        # While recording...
        if l_pool.record_running:
            l_pool.record_positions.append([pupil.gaze_coords[0], pupil.gaze_coords[1],pupil.norm_coords[0],pupil.norm_coords[1], bar.dt, g_pool.frame_count_record.value])
            if l_pool.writer is not None:
                l_pool.writer.write(cv2.cvtColor(img,cv2.cv.COLOR_BGR2RGB))

        # Done Recording: Save values and flip switch to off for recording
        if not g_pool.pos_record.value and l_pool.record_running:
            positions_path = path.join(l_pool.record_path, "gaze_positions.npy")
            cal_pt_cloud_path = path.join(l_pool.record_path, "cal_pt_cloud.npy")
            np.save(positions_path, np.asarray(l_pool.record_positions))
            try:
                np.save(cal_pt_cloud_path, np.asarray(pupil.pt_cloud))
            except:
                print "Warning: No calibration data associated with this recording."
            l_pool.writer = None
            l_pool.record_running = False



        ### GL-drawing
        clear_gl_screen()
        draw_gl_texture(img)

        if bar.draw_pupil and pupil.ellipse:
            pts = cv2.ellipse2Poly( (int(pupil.image_coords[0]),int(pupil.image_coords[1])),
                                    (int(pupil.ellipse["axes"][0]/2),int(pupil.ellipse["axes"][1]/2)),
                                    int(pupil.ellipse["angle"]),
                                    0,
                                    360,
                                    15)
            draw_gl_polyline(pts,(1.,0,0,.5))
            draw_gl_point_norm(pupil.norm_coords,(1.,0.,0.,0.5))

        bar.update()
        bar.draw()
        glfwSwapBuffers()


    #end while running
    print "EYE Process closed"
    r.save()
    bar.save()
    glfwCloseWindow()
    glfwTerminate()

