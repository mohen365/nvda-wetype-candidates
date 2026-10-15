// SPDX-License-Identifier: GPL-2.0-or-later
// Accessibility helper: only queries documented TSF interfaces on the focused
// editor thread in response to a private query. No keystroke capture or storage.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <msctf.h>
#include <oleauto.h>

static const GUID uiMgrId = {0xea1ea135,0x19df,0x11d7,{0xa6,0xd2,0,6,0x5b,0x84,0x43,0x5c}};
static const GUID candidateId = {0xea1ea138,0x19df,0x11d7,{0xa6,0xd2,0,6,0x5b,0x84,0x43,0x5c}};
// Use the Microsoft SDK ABI; some MinGW headers omit the candidate interface
// and incorrectly declare the enumerator's fetched output as a value.
struct CandidateElement: ITfUIElement {
 virtual HRESULT STDMETHODCALLTYPE GetUpdatedFlags(DWORD*)=0;
 virtual HRESULT STDMETHODCALLTYPE GetDocumentMgr(ITfDocumentMgr**)=0;
 virtual HRESULT STDMETHODCALLTYPE GetCount(UINT*)=0;
 virtual HRESULT STDMETHODCALLTYPE GetSelection(UINT*)=0;
 virtual HRESULT STDMETHODCALLTYPE GetString(UINT,BSTR*)=0;
 virtual HRESULT STDMETHODCALLTYPE GetPageIndex(UINT*,UINT,UINT*)=0;
 virtual HRESULT STDMETHODCALLTYPE SetPageIndex(UINT*,UINT)=0;
 virtual HRESULT STDMETHODCALLTYPE GetCurrentPage(UINT*)=0;
};
struct ElementEnum: IUnknown {
 virtual HRESULT STDMETHODCALLTYPE Clone(ElementEnum**)=0;
 virtual HRESULT STDMETHODCALLTYPE Next(ULONG,ITfUIElement**,ULONG*)=0;
 virtual HRESULT STDMETHODCALLTYPE Reset()=0;
 virtual HRESULT STDMETHODCALLTYPE Skip(ULONG)=0;
};
struct Reply {
 LONG sequence; DWORD threadId; LONG status; DWORD count; DWORD selected;
 DWORD length; WCHAR text[1024]; UINT currentPage; UINT pageCount; UINT pageIndexes[64];
};
typedef HRESULT (WINAPI *GetMgr)(ITfThreadMgr**);

extern "C" __declspec(dllexport) LRESULT CALLBACK candidateQueryHook(int code, WPARAM wp, LPARAM lp) {
 if (code==HC_ACTION && wp==PM_REMOVE && lp) {
  MSG* message=(MSG*)lp;
  static UINT query=RegisterWindowMessageW(L"NVDA.WeType.TSF.Query.v1");
  if (query && message->message==query && message->wParam && message->lParam) {
   GUITHREADINFO info={}; info.cbSize=sizeof(info);
   GetGUIThreadInfo(0,&info);
   DWORD foregroundThread=GetWindowThreadProcessId(info.hwndFocus,NULL);
   HWND candidate=FindWindowW(L"wetype.flutter.setting",L"wetype_candidate");
   if (foregroundThread==GetCurrentThreadId() && candidate && IsWindowVisible(candidate)) {
    WCHAR name[100]; wsprintfW(name,L"Local\\NVDAWeType_%lu_%lu",(DWORD)message->wParam,(DWORD)message->lParam);
    HANDLE mapping=OpenFileMappingW(FILE_MAP_WRITE|FILE_MAP_READ,FALSE,name);
    if (mapping) {
     Reply* reply=(Reply*)MapViewOfFile(mapping,FILE_MAP_WRITE|FILE_MAP_READ,0,0,sizeof(Reply));
     if(reply) {
      reply->threadId=GetCurrentThreadId(); reply->status=-1;
      reply->count=reply->selected=reply->length=0; reply->text[0]=0;
      reply->currentPage=reply->pageCount=0; ZeroMemory(reply->pageIndexes,sizeof(reply->pageIndexes));
      HMODULE module=GetModuleHandleW(L"msctf.dll");
      GetMgr getMgr=module?(GetMgr)GetProcAddress(module,"TF_GetThreadMgr"):NULL;
      ITfThreadMgr* mgr=NULL;
      if(getMgr && SUCCEEDED(getMgr(&mgr)) && mgr) {
       ITfUIElementMgr* ui=NULL;
       if(SUCCEEDED(mgr->QueryInterface(uiMgrId,(void**)&ui)) && ui) {
        ElementEnum* enumerator=NULL;
        if(SUCCEEDED(ui->EnumUIElements((IEnumTfUIElements**)&enumerator)) && enumerator) {
         for(int i=0;i<20;i++) {
          ITfUIElement* el=NULL; ULONG fetched=0;
          if(enumerator->Next(1,&el,&fetched)!=S_OK || !fetched || !el) break;
          CandidateElement* candidates=NULL;
          if(SUCCEEDED(el->QueryInterface(candidateId,(void**)&candidates)) && candidates) {
           UINT count=0,selected=0; BSTR text=NULL;
           candidates->GetCurrentPage(&reply->currentPage);
           candidates->GetPageIndex(reply->pageIndexes,64,&reply->pageCount);
           if(SUCCEEDED(candidates->GetCount(&count)) && count>0 && count<=4096 &&
              SUCCEEDED(candidates->GetSelection(&selected)) && selected<count &&
              SUCCEEDED(candidates->GetString(selected,&text)) && text) {
            UINT length=SysStringLen(text);
            if(length>0 && length<1024) {
             reply->count=count; reply->selected=selected; reply->length=length;
             CopyMemory(reply->text,text,length*sizeof(WCHAR)); reply->text[length]=0;
             reply->status=0;
            }
           }
           if(text) SysFreeString(text);
           candidates->Release();
          }
          el->Release();
          if(reply->status==0) break;
         }
         enumerator->Release();
        }
        ui->Release();
       }
       mgr->Release();
      }
      InterlockedExchange(&reply->sequence,(LONG)message->lParam);
      UnmapViewOfFile(reply);
     }
     CloseHandle(mapping);
    }
   }
  }
 }
 return CallNextHookEx(NULL,code,wp,lp);
}
