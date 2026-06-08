

import cv2 
import numpy as np 
import requests 
import json 
import threading 
import sys 
import time 
import os 
from typing import Optional 

try :
    from PIL import ImageFont ,ImageDraw ,Image as PILImage 
    PILLOW_OK =True 
except ImportError :
    PILLOW_OK =False 
    print ("[!] Pillow не найден — кириллица на экране недоступна.")
    print ("    Установите: pip install pillow\n")


try :
    import tkinter as tk 
    from tkinter import filedialog 
    TKINTER_OK =True 
except ImportError :
    TKINTER_OK =False 


LM_STUDIO_URL ="http://localhost:1234/v1/chat/completions"
MODEL_NAME ="llama-3.1-8b"
CAMERA_INDEX =0 
WINDOW_NAME ="AI Camera Editor"

FONT_PATH_OVERRIDE =""


MENU =[
(1 ,"Поверни на 90 градусов",{"op":"rotate","angle":90 }),
(2 ,"Отрази по горизонтали (зеркало)",{"op":"flip","axis":"horizontal"}),
(3 ,"Чёрно-белое",{"op":"grayscale"}),
(4 ,"Выдели красный канал",{"op":"channel","channel":"red"}),
(5 ,"Выдели зелёный канал",{"op":"channel","channel":"green"}),
(6 ,"Выдели синий канал",{"op":"channel","channel":"blue"}),
(7 ,"Увеличь яркость",{"op":"brightness","delta":60 }),
(8 ,"Уменьши до 50%",{"op":"resize","scale":0.5 }),
(9 ,"Добавь размытие",{"op":"blur","radius":9 }),
(10 ,"Инвертируй цвета",{"op":"invert"}),
(11 ,"Повысь контраст",{"op":"contrast","alpha":1.7 }),
(12 ,"Сепия",{"op":"sepia"}),
(13 ,"Выдели контуры (Canny)",{"op":"edge"}),
(14 ,"Повысь резкость",{"op":"sharpen"}),
(15 ,"Эффект тиснения",{"op":"emboss"}),
(16 ,"Увеличь до 200%",{"op":"resize","scale":2.0 }),
(0 ,"Сбросить все эффекты",{"op":"reset"}),
]

MENU_BY_NUM ={str (item [0 ]):item [2 ]for item in MENU }


SYSTEM_PROMPT ="""Ты — движок обработки изображений. Пользователь вводит текстовую команду.
Верни ТОЛЬКО валидный JSON-объект (без markdown, без пояснений).

Операции:
{"op":"rotate","angle":90}          — поворот. angle = целое число.
{"op":"flip","axis":"horizontal"}   — отражение: "horizontal" или "vertical"
{"op":"grayscale"}                  — чёрно-белое
{"op":"channel","channel":"red"}    — канал: "red","green","blue"
{"op":"brightness","delta":60}      — яркость -255..255
{"op":"resize","scale":0.5}         — масштаб 0.1..3
{"op":"blur","radius":9}            — размытие 3..31
{"op":"invert"}                     — инверсия/негатив
{"op":"contrast","alpha":1.7}       — контраст 0.1..3
{"op":"sepia"}                      — сепия
{"op":"sharpen"}                    — резкость
{"op":"edge"}                       — контуры Canny
{"op":"emboss"}                     — тиснение
{"op":"threshold"}                  — бинаризация
{"op":"resize","scale":2.0}          — увеличение до 200%
{"op":"crop","x":0,"y":0,"w":640,"h":480} — обрезка области
{"op":"reset"}                      — сброс всех эффектов

Только JSON. Если совсем непонятно — {"op":"unknown"}.
"""


def find_font ()->str :
    if FONT_PATH_OVERRIDE and os .path .exists (FONT_PATH_OVERRIDE ):
        return FONT_PATH_OVERRIDE 

    candidates =[]

    if sys .platform =="win32":
        win_fonts =os .path .join (os .environ .get ("WINDIR","C:/Windows"),"Fonts")
        candidates =[
        os .path .join (win_fonts ,f )
        for f in ["arial.ttf","segoeui.ttf","tahoma.ttf",
        "calibri.ttf","verdana.ttf","cour.ttf"]
        ]
    elif sys .platform =="darwin":
        candidates =[
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        ]
    else :
        candidates =[
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]

    for p in candidates :
        if os .path .exists (p ):
            return p 
    return ""

FONT_FILE =find_font ()if PILLOW_OK else ""


def _pil_font (size :int ):
    if not PILLOW_OK :
        return None 
    try :
        if FONT_FILE :
            return ImageFont .truetype (FONT_FILE ,size )
        return ImageFont .load_default ()
    except Exception :
        return ImageFont .load_default ()

_font_cache :dict ={}

def get_font (size :int ):
    if size not in _font_cache :
        _font_cache [size ]=_pil_font (size )
    return _font_cache [size ]


def put_text_utf8 (frame :np .ndarray ,text :str ,
pos :tuple ,size :int ,
color_bgr :tuple ,bold :bool =False )->np .ndarray :
    if not PILLOW_OK :
        cv2 .putText (frame ,text ,pos ,
        cv2 .FONT_HERSHEY_SIMPLEX ,size /30 ,
        color_bgr ,1 +int (bold ),cv2 .LINE_AA )
        return frame 

    pil_img =PILImage .fromarray (cv2 .cvtColor (frame ,cv2 .COLOR_BGR2RGB ))
    draw =ImageDraw .Draw (pil_img )
    font =get_font (size )
    rgb =(color_bgr [2 ],color_bgr [1 ],color_bgr [0 ])

    draw .text (pos ,text ,font =font ,fill =rgb )
    if bold :
        draw .text ((pos [0 ]+1 ,pos [1 ]),text ,font =font ,fill =rgb )

    return cv2 .cvtColor (np .array (pil_img ),cv2 .COLOR_RGB2BGR )






class Mode :
    CAMERA ="camera"
    PHOTO ="photo"


class State :
    def __init__ (self ):
        self .effects :list [dict ]=[]
        self .lock =threading .Lock ()
        self .status ="Готов. Введите номер команды в терминале."
        self .status_color =(0 ,220 ,120 )
        self .processing =False 
        self .save_index =0 


        self .mode =Mode .CAMERA 
        self .photo_path =""
        self .photo_frame =None 
        self .load_request =False 
        self .crop_request =False 

state =State ()






SUPPORTED_EXTS =(".jpg",".jpeg",".png",".bmp",".tiff",".tif",".webp")

def open_file_dialog ()->str :

    if not TKINTER_OK :
        return ""
    try :
        root =tk .Tk ()
        root .withdraw ()
        root .attributes ("-topmost",True )
        path =filedialog .askopenfilename (
        title ="Выберите изображение",
        filetypes =[
        ("Изображения","*.jpg *.jpeg *.png *.bmp *.tiff *.tif *.webp"),
        ("Все файлы","*.*"),
        ]
        )
        root .destroy ()
        return path or ""
    except Exception as ex :
        print (f"[диалог] Ошибка tkinter: {ex }")
        return ""


def load_photo (path :str )->bool :

    path =path .strip ().strip ('"').strip ("'")
    if not path :
        return False 
    if not os .path .exists (path ):
        state .status =f"Файл не найден: {os .path .basename (path )}"
        state .status_color =(50 ,50 ,240 )
        print (f"[!] Файл не найден: {path }")
        return False 

    ext =os .path .splitext (path )[1 ].lower ()
    if ext not in SUPPORTED_EXTS :
        state .status =f"Формат не поддерживается: {ext }"
        state .status_color =(50 ,50 ,240 )
        print (f"[!] Неподдерживаемый формат: {ext }")
        return False 


    try :
        if PILLOW_OK :
            pil_img =PILImage .open (path )

            try :
                from PIL import ImageOps 
                pil_img =ImageOps .exif_transpose (pil_img )
            except Exception :
                pass 
            pil_img =pil_img .convert ("RGB")
            frame =cv2 .cvtColor (np .array (pil_img ),cv2 .COLOR_RGB2BGR )
        else :
            frame =cv2 .imread (path )
            if frame is None :
                raise ValueError ("cv2.imread вернул None")
    except Exception as ex :
        state .status =f"Ошибка загрузки: {os .path .basename (path )}"
        state .status_color =(50 ,50 ,240 )
        print (f"[!] Ошибка загрузки фото: {ex }")
        return False 

    with state .lock :
        state .photo_frame =frame 
        state .photo_path =path 
        state .effects .clear ()
        state .mode =Mode .PHOTO 

    name =os .path .basename (path )
    h ,w =frame .shape [:2 ]
    state .status =f"Фото загружено: {name }  ({w }×{h })  |  K — обрезать"
    state .status_color =(0 ,220 ,120 )
    print (f"[Фото] Загружено: {path }  ({w }×{h })")
    return True 


def switch_to_camera ():
    with state .lock :
        state .mode =Mode .CAMERA 
        state .photo_frame =None 
        state .photo_path =""
        state .effects .clear ()
    state .status ="Режим камеры. Введите номер команды."
    state .status_color =(0 ,220 ,120 )
    print ("[Режим] Камера")


def run_crop_tool (base_frame :np .ndarray ):

    CROP_WIN ="Crop Tool"


    with state .lock :
        effs =list (state .effects )
    working =apply_effects (base_frame ,effs )


    disp_h ,disp_w =working .shape [:2 ]
    max_dim =1100 
    scale_f =1.0 
    if disp_w >max_dim or disp_h >max_dim :
        scale_f =min (max_dim /disp_w ,max_dim /disp_h )
        disp_w =int (disp_w *scale_f )
        disp_h =int (disp_h *scale_f )
        display_img =cv2 .resize (working ,(disp_w ,disp_h ))
    else :
        display_img =working .copy ()


    drag ={"start":None ,"end":None ,"drawing":False }
    result ={"rect":None }

    def on_mouse (event ,x ,y ,flags ,_ ):
        x =max (0 ,min (x ,disp_w -1 ))
        y =max (0 ,min (y ,disp_h -1 ))
        if event ==cv2 .EVENT_LBUTTONDOWN :
            drag ["start"]=(x ,y )
            drag ["end"]=(x ,y )
            drag ["drawing"]=True 
        elif event ==cv2 .EVENT_MOUSEMOVE and drag ["drawing"]:
            drag ["end"]=(x ,y )
        elif event ==cv2 .EVENT_LBUTTONUP :
            drag ["end"]=(x ,y )
            drag ["drawing"]=False 

    cv2 .namedWindow (CROP_WIN ,cv2 .WINDOW_AUTOSIZE )
    cv2 .setMouseCallback (CROP_WIN ,on_mouse )

    state .status ="Обрезка: выделите область мышью, Enter — применить, ESC — отмена"
    state .status_color =(0 ,200 ,255 )

    while True :
        canvas =display_img .copy ()


        if drag ["start"]and drag ["end"]:
            x1 ,y1 =drag ["start"]
            x2 ,y2 =drag ["end"]

            mask =canvas .copy ()
            cv2 .rectangle (mask ,(0 ,0 ),(disp_w ,disp_h ),(0 ,0 ,0 ),-1 )
            cv2 .rectangle (mask ,
            (min (x1 ,x2 ),min (y1 ,y2 )),
            (max (x1 ,x2 ),max (y1 ,y2 )),
            (255 ,255 ,255 ),-1 )
            canvas =cv2 .addWeighted (canvas ,0.6 ,cv2 .bitwise_and (display_img ,mask ),0.4 ,0 )
            canvas [min (y1 ,y2 ):max (y1 ,y2 ),min (x1 ,x2 ):max (x1 ,x2 )]=display_img [min (y1 ,y2 ):max (y1 ,y2 ),min (x1 ,x2 ):max (x1 ,x2 )]
            cv2 .rectangle (canvas ,
            (min (x1 ,x2 ),min (y1 ,y2 )),
            (max (x1 ,x2 ),max (y1 ,y2 )),
            (0 ,255 ,100 ),2 )

            ow =int (abs (x2 -x1 )/scale_f )
            oh =int (abs (y2 -y1 )/scale_f )
            label =f"{ow } x {oh } px"
            canvas =put_text_utf8 (canvas ,label ,
            (min (x1 ,x2 )+4 ,min (y1 ,y2 )-24 ),
            20 ,(0 ,255 ,100 ))


        canvas =put_text_utf8 (canvas ,
        "Enter — применить обрезку        ESC — отмена",
        (8 ,disp_h -14 ),19 ,(180 ,180 ,180 ))

        cv2 .imshow (CROP_WIN ,canvas )

        key =cv2 .waitKey (20 )&0xFF 

        if key ==27 :
            state .status ="Обрезка отменена"
            state .status_color =(150 ,150 ,150 )
            break 

        elif key ==13 :
            if drag ["start"]and drag ["end"]:
                x1 ,y1 =drag ["start"]
                x2 ,y2 =drag ["end"]

                ox =int (min (x1 ,x2 )/scale_f )
                oy =int (min (y1 ,y2 )/scale_f )
                ow =int (abs (x2 -x1 )/scale_f )
                oh =int (abs (y2 -y1 )/scale_f )
                if ow >5 and oh >5 :
                    result ["rect"]=(ox ,oy ,ow ,oh )
                    state .status =f"✓ Обрезка применена: {ow }×{oh } px"
                    state .status_color =(0 ,220 ,120 )
                    print (f"[Обрезка] x={ox } y={oy } w={ow } h={oh }")
                else :
                    state .status ="Область слишком маленькая"
                    state .status_color =(50 ,50 ,240 )
            else :
                state .status ="Область не выделена"
                state .status_color =(50 ,50 ,240 )
            break 

    cv2 .destroyWindow (CROP_WIN )


    if result ["rect"]:
        ox ,oy ,ow ,oh =result ["rect"]


        cropped =apply_effects (base_frame ,effs )
        h0 ,w0 =cropped .shape [:2 ]
        ox =max (0 ,min (ox ,w0 -1 ))
        oy =max (0 ,min (oy ,h0 -1 ))
        ow =min (ow ,w0 -ox )
        oh =min (oh ,h0 -oy )
        cropped =cropped [oy :oy +oh ,ox :ox +ow ]
        with state .lock :
            state .photo_frame =cropped 
            state .effects .clear ()
            state .mode =Mode .PHOTO 






def ask_llm (user_text :str )->Optional [dict ]:
    payload ={
    "model":MODEL_NAME ,
    "messages":[
    {"role":"system","content":SYSTEM_PROMPT },
    {"role":"user","content":user_text }
    ],
    "temperature":0.1 ,
    "max_tokens":100 ,
    "stream":False 
    }
    try :
        resp =requests .post (LM_STUDIO_URL ,json =payload ,timeout =30 )
        resp .raise_for_status ()
        raw =resp .json ()["choices"][0 ]["message"]["content"].strip ()
        raw =raw .replace ("```json","").replace ("```","").strip ()
        s ,e =raw .find ("{"),raw .rfind ("}")+1 
        if s ==-1 or e ==0 :
            return None 
        return json .loads (raw [s :e ])
    except requests .exceptions .ConnectionError :
        return {"op":"_connection_error"}
    except Exception as ex :
        print (f"[LLM ошибка] {ex }")
        return None 






def apply_effects (frame :np .ndarray ,effects :list [dict ])->np .ndarray :
    result =frame .copy ()
    for eff in effects :
        op =eff .get ("op")
        try :
            if op =="rotate":
                angle =eff .get ("angle",90 )
                h ,w =result .shape [:2 ]
                cx ,cy =w //2 ,h //2 
                M =cv2 .getRotationMatrix2D ((cx ,cy ),-angle ,1.0 )
                cos_a ,sin_a =abs (M [0 ,0 ]),abs (M [0 ,1 ])
                nw =int (h *sin_a +w *cos_a )
                nh =int (h *cos_a +w *sin_a )
                M [0 ,2 ]+=(nw /2 )-cx 
                M [1 ,2 ]+=(nh /2 )-cy 
                result =cv2 .warpAffine (result ,M ,(nw ,nh ))

            elif op =="flip":
                code =1 if eff .get ("axis","horizontal")=="horizontal"else 0 
                result =cv2 .flip (result ,code )

            elif op =="grayscale":
                result =cv2 .cvtColor (cv2 .cvtColor (result ,cv2 .COLOR_BGR2GRAY ),cv2 .COLOR_GRAY2BGR )

            elif op =="channel":
                idx ={"blue":0 ,"green":1 ,"red":2 }.get (eff .get ("channel","red"),2 )
                mask =np .zeros_like (result )
                mask [:,:,idx ]=result [:,:,idx ]
                result =mask 

            elif op =="brightness":
                result =cv2 .convertScaleAbs (result ,alpha =1.0 ,beta =eff .get ("delta",60 ))

            elif op =="resize":
                sc =float (eff .get ("scale",0.5 ))
                h ,w =result .shape [:2 ]
                result =cv2 .resize (result ,(max (1 ,int (w *sc )),max (1 ,int (h *sc ))))

            elif op =="blur":
                r =int (eff .get ("radius",9 ))
                r =r if r %2 ==1 else r +1 
                result =cv2 .GaussianBlur (result ,(r ,r ),0 )

            elif op =="invert":
                result =cv2 .bitwise_not (result )

            elif op =="contrast":
                result =cv2 .convertScaleAbs (result ,alpha =float (eff .get ("alpha",1.7 )),beta =0 )

            elif op =="sepia":
                k =np .array ([[0.131 ,0.534 ,0.272 ],[0.168 ,0.686 ,0.349 ],[0.189 ,0.769 ,0.393 ]])
                result =np .clip (cv2 .transform (result ,k ),0 ,255 ).astype (np .uint8 )

            elif op =="sharpen":
                result =cv2 .filter2D (result ,-1 ,np .array ([[-1 ,-1 ,-1 ],[-1 ,9 ,-1 ],[-1 ,-1 ,-1 ]]))

            elif op =="edge":
                gray =cv2 .cvtColor (result ,cv2 .COLOR_BGR2GRAY )
                result =cv2 .cvtColor (cv2 .Canny (gray ,100 ,200 ),cv2 .COLOR_GRAY2BGR )

            elif op =="emboss":
                result =cv2 .filter2D (result ,-1 ,np .array ([[-2 ,-1 ,0 ],[-1 ,1 ,1 ],[0 ,1 ,2 ]]))

            elif op =="threshold":
                gray =cv2 .cvtColor (result ,cv2 .COLOR_BGR2GRAY )
                _ ,thr =cv2 .threshold (gray ,0 ,255 ,cv2 .THRESH_BINARY +cv2 .THRESH_OTSU )
                result =cv2 .cvtColor (thr ,cv2 .COLOR_GRAY2BGR )

            elif op =="crop":
                h ,w =result .shape [:2 ]
                x =max (0 ,int (eff .get ("x",0 )))
                y =max (0 ,int (eff .get ("y",0 )))
                cw =min (int (eff .get ("w",w )),w -x )
                ch =min (int (eff .get ("h",h )),h -y )
                if cw >1 and ch >1 :
                    result =result [y :y +ch ,x :x +cw ]

        except Exception as ex :
            print (f"[Эффект {op }] {ex }")
    return result 


OP_NAMES ={
"rotate":"Поворот","flip":"Отражение","grayscale":"Ч/Б",
"channel":"Канал","brightness":"Яркость","resize":"Масштаб",
"blur":"Размытие","invert":"Инверсия","contrast":"Контраст",
"sepia":"Сепия","sharpen":"Резкость","edge":"Контуры",
"emboss":"Тиснение","threshold":"Бинаризация","reset":"Сброс",
"crop":"Обрезка",
}






def draw_hud (frame :np .ndarray )->np .ndarray :
    h ,w =frame .shape [:2 ]

    overlay =frame .copy ()
    cv2 .rectangle (overlay ,(0 ,h -90 ),(w ,h ),(0 ,0 ,0 ),-1 )
    cv2 .addWeighted (overlay ,0.6 ,frame ,0.4 ,0 ,frame )

    frame =put_text_utf8 (frame ,state .status ,(12 ,h -62 ),20 ,state .status_color ,bold =True )


    if state .mode ==Mode .PHOTO :
        hint ="ESC — выход    S — сохранить    TAB — сброс    ← — отмена    O — фото    K — обрезать    Z — увеличить    C — камера"
    else :
        hint ="ESC — выход    S — сохранить    TAB — сброс    ← — отмена    O — фото    K — обрезать    Z — увеличить"

    frame =put_text_utf8 (frame ,hint ,(12 ,h -30 ),17 ,(150 ,150 ,150 ))

    with state .lock :
        effs =list (state .effects )
        cur_mode =state .mode 
        photo_path =state .photo_path 


    mode_label ="📷 КАМЕРА"if cur_mode ==Mode .CAMERA else "🖼  ФОТО"
    mode_color =(0 ,200 ,255 )if cur_mode ==Mode .CAMERA else (80 ,255 ,180 )
    frame =put_text_utf8 (frame ,mode_label ,(w -160 ,10 ),18 ,mode_color ,bold =True )


    if cur_mode ==Mode .PHOTO and photo_path :
        fname =os .path .basename (photo_path )
        if len (fname )>40 :
            fname ="..."+fname [-37 :]
        frame =put_text_utf8 (frame ,fname ,(w -160 ,32 ),15 ,(180 ,180 ,180 ))

    if effs :
        parts =[]
        for e in effs :
            name =OP_NAMES .get (e ["op"],e ["op"])
            if e ["op"]=="rotate":name +=f" {e .get ('angle',90 )}°"
            elif e ["op"]=="channel":name +=f" ({e .get ('channel','')})"
            elif e ["op"]=="resize":name +=f" ×{e .get ('scale','')}"
            parts .append (name )
        label ="Эффекты: "+" → ".join (parts )
        if len (label )>100 :
            label =label [:97 ]+"..."
        cv2 .rectangle (frame ,(0 ,0 ),(w ,38 ),(0 ,0 ,0 ),-1 )
        frame =put_text_utf8 (frame ,label ,(12 ,10 ),18 ,(80 ,210 ,255 ))

    if state .processing :
        sp =["|","/","—","\\"][int (time .time ()*4 )%4 ]
        frame =put_text_utf8 (frame ,f"{sp } ИИ думает...",(12 ,44 ),18 ,(0 ,220 ,255 ))

    return frame 






def apply_op (op_dict :dict ,source :str =""):
    op =op_dict .get ("op","unknown")
    if op =="unknown":
        state .status ="Команда не распознана"
        state .status_color =(50 ,180 ,240 )
        return 
    if op =="_connection_error":
        state .status ="Ошибка: LM Studio недоступен (localhost:1234)"
        state .status_color =(50 ,50 ,240 )
        return 

    with state .lock :
        if op =="reset":
            state .effects .clear ()
            name ="Все эффекты сброшены"
        else :
            state .effects .append (op_dict )
            name =OP_NAMES .get (op ,op )+" применён"

    state .status =f"✓ {name }"
    state .status_color =(0 ,220 ,120 )
    tag =f"[{source }]"if source else "[ОК]"
    print (f"{tag } {name }  ←  {json .dumps (op_dict ,ensure_ascii =False )}")


def undo_last_effect ():

    with state .lock :
        if state .effects :
            removed =state .effects .pop ()
            name =OP_NAMES .get (removed ["op"],removed ["op"])
            state .status =f"↩ Отменено: {name }"
            state .status_color =(0 ,200 ,255 )
            print (f"[Отмена] {name }  ←  {json .dumps (removed ,ensure_ascii =False )}")
        else :
            state .status ="Нечего отменять"
            state .status_color =(150 ,150 ,150 )


def process_text_command (user_input :str ):
    state .processing =True 
    state .status =f"Думаю: «{user_input }»"
    state .status_color =(0 ,200 ,255 )

    result =ask_llm (user_input )
    if result is None :
        state .status ="Не удалось распознать команду"
        state .status_color =(50 ,50 ,240 )
    else :
        apply_op (result ,source ="ИИ")
    state .processing =False 






def print_menu ():
    print ("\n"+"="*66 )
    print ("   AI Camera Editor  —  LM Studio llama 3.1 8B + OpenCV")
    print ("="*66 )
    print ("  Введите НОМЕР команды и нажмите Enter")
    print ("  Или введите текст — ИИ сам определит операцию\n")
    for num ,desc ,_ in MENU :
        print (f"  [{num :2d}]  {desc }")
    print ()
    print ("  ── Специальные команды ──────────────────────────────────")
    print ("  [photo] или [p]   — загрузить фото из файла (диалог)")
    print ("  [photo путь]      — загрузить фото по пути напрямую")
    print ("  [camera] или [c]  — вернуться к режиму камеры")
    print ("  [crop]  или [k]   — обрезать текущий кадр/фото мышью")
    print ()
    print ("  ── Горячие клавиши в окне камеры ────────────────────────")
    print ("  ESC / Ctrl+C     — выход")
    print ("  Ctrl+S           — сохранить кадр (snapshot_NNNN.png)")
    print ("  TAB              — сбросить все эффекты")
    print ("  ← (стрелка влево) — отменить последний эффект")
    print ("  Z                — увеличить ×2")
    print ("  O                — загрузить фото (диалог)")
    print ("  K                — обрезать (интерактивно мышью)")
    print ("  C                — вернуться к камере")
    print ("  1 - 9            — быстрый вызов команды из меню")
    print ("="*66 +"\n")


def handle_photo_command (raw :str ):

    parts =raw .split (None ,1 )
    if len (parts )==2 :

        path =parts [1 ]
        load_photo (path )
    else :

        if TKINTER_OK :
            print ("  [Диалог] Открываю диалог выбора файла...")
            path =open_file_dialog ()
            if path :
                load_photo (path )
            else :
                print ("  [!] Файл не выбран")
                state .status ="Файл не выбран"
                state .status_color =(150 ,150 ,150 )
        else :

            print ("  [!] tkinter недоступен. Введите путь к файлу:")
            try :
                path =input ("  Путь >>> ").strip ()
                if path :
                    load_photo (path )
                else :
                    print ("  [!] Путь не введён")
            except (EOFError ,KeyboardInterrupt ):
                pass 


def input_thread ():
    print_menu ()
    while True :
        try :
            raw =input (">>> ").strip ()
        except (EOFError ,KeyboardInterrupt ):
            cv2 .destroyAllWindows ()
            sys .exit (0 )

        if not raw :
            continue 

        lo =raw .lower ()

        if lo in ("q","quit","exit","выход"):
            cv2 .destroyAllWindows ()
            sys .exit (0 )


        if lo in ("r","0","reset","сброс"):
            apply_op ({"op":"reset"},source ="меню")
            continue 


        if lo in ("c","camera","камера"):
            switch_to_camera ()
            continue 


        if lo .startswith ("photo")or lo .startswith ("фото")or lo =="p":
            handle_photo_command (raw )
            continue 


        if lo in ("crop","обрезать","k"):
            with state .lock :
                state .crop_request =True 
            continue 


        if raw .isdigit ():
            op =MENU_BY_NUM .get (raw )
            if op :
                item =next (i for i in MENU if str (i [0 ])==raw )
                print (f"  → {item [1 ]}")
                apply_op (dict (op ),source ="меню")
            else :
                print (f"  [!] Нет команды с номером {raw }. Введите 0-15.")
            continue 


        if os .path .exists (raw ):
            ext =os .path .splitext (raw )[1 ].lower ()
            if ext in SUPPORTED_EXTS :
                load_photo (raw )
                continue 


        if state .processing :
            print ("  [!] Ещё обрабатывается предыдущая команда, подождите...")
            continue 

        t =threading .Thread (target =process_text_command ,args =(raw ,),daemon =True )
        t .start ()






EXIT_KEYS ={27 }
SAVE_KEYS ={19 }
RESET_KEYS ={9 }


LEFT_ARROW_CODES ={
2424832 ,
65361 ,
63234 ,
}

PHOTO_KEYS ={ord ('o'),ord ('O')}
CROP_KEYS ={ord ('k'),ord ('K')}
ZOOM_KEYS ={ord ('z'),ord ('Z')}
CAM_KEYS ={ord ('c'),ord ('C')}
DIGIT_KEYS ={ord (str (i )):str (i )for i in range (0 ,10 )}






def main ():
    cap =cv2 .VideoCapture (CAMERA_INDEX )
    if not cap .isOpened ():
        print (f"[!] Камера {CAMERA_INDEX } не открылась. Попробуйте CAMERA_INDEX = 1")
        sys .exit (1 )

    cap .set (cv2 .CAP_PROP_FRAME_WIDTH ,1280 )
    cap .set (cv2 .CAP_PROP_FRAME_HEIGHT ,720 )
    cap .set (cv2 .CAP_PROP_FPS ,30 )

    threading .Thread (target =input_thread ,daemon =True ).start ()

    while True :

        with state .lock :
            cur_mode =state .mode 
            photo_frame =state .photo_frame 
            effs =list (state .effects )
            load_req =state .load_request 
            crop_req =state .crop_request 
            if load_req :
                state .load_request =False 
            if crop_req :
                state .crop_request =False 


        if load_req and TKINTER_OK :
            threading .Thread (target =lambda :(
            load_photo (p )if (p :=open_file_dialog ())else None 
            ),daemon =True ).start ()
        elif load_req and not TKINTER_OK :
            print ("  [!] tkinter недоступен. Введите: photo <путь к файлу>")

        if cur_mode ==Mode .PHOTO :
            if photo_frame is None :
                frame =np .zeros ((480 ,640 ,3 ),dtype =np .uint8 )
                frame =put_text_utf8 (frame ,
                "Нет фото. Введите 'photo' в терминале.",
                (30 ,220 ),22 ,(150 ,150 ,150 ))
            else :
                frame =photo_frame .copy ()
        else :
            ret ,frame =cap .read ()
            if not ret :
                print ("[!] Не удалось получить кадр.")
                break 

            frame =cv2 .flip (frame ,1 )


        if crop_req :

            if cur_mode ==Mode .CAMERA :
                with state .lock :
                    state .photo_frame =frame .copy ()
                    state .mode =Mode .PHOTO 
                    state .photo_path ="снимок (обрезка)"
                base_for_crop =frame .copy ()
            else :
                base_for_crop =photo_frame .copy ()if photo_frame is not None else frame .copy ()
            run_crop_tool (base_for_crop )

            with state .lock :
                photo_frame =state .photo_frame 
                effs =list (state .effects )
            continue 

        processed =apply_effects (frame ,effs )
        display =draw_hud (processed .copy ())

        cv2 .imshow (WINDOW_NAME ,display )

        key_ex =cv2 .waitKeyEx (1 )
        key =key_ex &0xFF 

        if key_ex ==-1 :
            continue 

        if key in EXIT_KEYS :
            break 

        elif key in SAVE_KEYS :
            fname =f"snapshot_{state .save_index :04d}.png"
            cv2 .imwrite (fname ,processed )
            state .save_index +=1 
            state .status =f"Сохранено: {fname }"
            state .status_color =(0 ,220 ,120 )
            print (f"[Снимок] {fname }")

        elif key in RESET_KEYS :
            apply_op ({"op":"reset"},source ="клавиша")

        elif key_ex in LEFT_ARROW_CODES :
            undo_last_effect ()

        elif key in PHOTO_KEYS :

            with state .lock :
                state .load_request =True 

        elif key in CROP_KEYS :

            with state .lock :
                state .crop_request =True 

        elif key in ZOOM_KEYS :

            apply_op ({"op":"resize","scale":2.0 },source ="клавиша Z")

        elif key in CAM_KEYS :
            switch_to_camera ()

        elif key in DIGIT_KEYS :
            num_str =DIGIT_KEYS [key ]
            op =MENU_BY_NUM .get (num_str )
            if op :
                item =next (i for i in MENU if str (i [0 ])==num_str )
                print (f"  [клавиша {num_str }] {item [1 ]}")
                apply_op (dict (op ),source =f"клавиша {num_str }")

    cap .release ()
    cv2 .destroyAllWindows ()
    print ("\nДо свидания!")


if __name__ =="__main__":
    main ()