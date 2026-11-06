#!/usr/bin/env python3
"""Validate the benchmark harness without any model.

Writes two synthetic "model answers" per task into results/_selftest/code/:
  ref__<id>      reference-correct solution  -> must PASS
  vulnorig__<id> the original source          -> real vuln must FAIL,
                                                 traps (v07,v08) must PASS
Then run:  python autograde.py --run _selftest
Expected: all ref__ PASS; vulnorig__ v01..v06 FAIL; vulnorig__ v07,v08 PASS;
coding tasks have no vulnorig entry.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
TASKS = ROOT / "tasks"
OUT = ROOT / "results" / "_selftest" / "code"

REF = {
"c01": ("c", r'''
#include <stdint.h>
int32_t safe_add(int32_t a, int32_t b, int *overflow){
    int64_t r=(int64_t)a+(int64_t)b;
    *overflow=(r<INT32_MIN||r>INT32_MAX)?1:0;
    return (int32_t)r;
}'''),
"c02": ("c", r'''
#include <stddef.h>
size_t rle_encode(const unsigned char*in,size_t n,unsigned char*out,size_t cap){
    size_t w=0,i=0;
    while(i<n){unsigned char v=in[i];size_t run=1;
        while(i+run<n&&in[i+run]==v&&run<255)run++;
        if(w+2>cap)return (size_t)-1;
        out[w++]=(unsigned char)run;out[w++]=v;i+=run;}
    return w;
}'''),
"c03": ("c", r'''
#include <stddef.h>
long bsearch_first(const int*a,size_t n,int key){
    size_t lo=0,hi=n;long res=-1;
    while(lo<hi){size_t mid=lo+(hi-lo)/2;
        if(a[mid]<key)lo=mid+1;
        else{if(a[mid]==key)res=(long)mid;hi=mid;}}
    return res;
}'''),
"c04": ("cpp", r'''
#include <string>
#include <cctype>
std::string compress_spaces(const std::string& s){
    std::string out;bool in_ws=false,started=false;
    for(unsigned char c:s){
        if(std::isspace(c)){in_ws=true;continue;}
        if(in_ws&&started)out.push_back(' ');
        out.push_back((char)c);started=true;in_ws=false;}
    return out;
}'''),
"c05": ("cpp", r'''
#include <vector>
#include <utility>
#include <algorithm>
std::vector<std::pair<int,int>> merge_intervals(std::vector<std::pair<int,int>> v){
    std::sort(v.begin(),v.end());
    std::vector<std::pair<int,int>> out;
    for(auto&iv:v){
        if(!out.empty()&&iv.first<=out.back().second)
            out.back().second=std::max(out.back().second,iv.second);
        else out.push_back(iv);}
    return out;
}'''),
"c06": ("cpp", r'''
#include <string>
#include <vector>
std::vector<std::string> split_csv(const std::string& line){
    std::vector<std::string> out;std::string cur;size_t i=0,n=line.size();
    while(true){cur.clear();
        if(i<n&&line[i]=='"'){++i;
            while(i<n){
                if(line[i]=='"'){
                    if(i+1<n&&line[i+1]=='"'){cur.push_back('"');i+=2;}
                    else{++i;break;}
                } else cur.push_back(line[i++]);}
            while(i<n&&line[i]!=',')++i;
        } else { while(i<n&&line[i]!=',')cur.push_back(line[i++]); }
        out.push_back(cur);
        if(i<n&&line[i]==','){++i;continue;}
        break;}
    return out;
}'''),
"c07": ("cs", r'''
public static class Solution{
    public static int CompareVersions(string a,string b){
        var pa=a.Split('.');var pb=b.Split('.');
        int n=System.Math.Max(pa.Length,pb.Length);
        for(int i=0;i<n;i++){
            int va=i<pa.Length?int.Parse(pa[i]):0;
            int vb=i<pb.Length?int.Parse(pb[i]):0;
            if(va!=vb)return va<vb?-1:1;}
        return 0;
    }
}'''),
"c08": ("cs", r'''
using System.Collections.Generic;
public static class Solution{
    public static bool IsBalanced(string s){
        var st=new Stack<char>();
        foreach(char c in s){
            if(c=='('||c=='['||c=='{')st.Push(c);
            else if(c==')'||c==']'||c=='}'){
                if(st.Count==0)return false;char o=st.Pop();
                if((c==')'&&o!='(')||(c==']'&&o!='[')||(c=='}'&&o!='{'))return false;}}
        return st.Count==0;
    }
}'''),
"v01": ("c", r'''
#include <stddef.h>
#include <string.h>
int parse_record(const unsigned char*in,size_t in_len,char out[32]){
    if(in_len==0){out[0]='\0';return 0;}
    size_t avail=in_len-1,len=in[0];
    if(len>avail)len=avail;
    if(len>31)len=31;
    memcpy(out,in+1,len);out[len]='\0';return (int)len;
}'''),
"v02": ("c", r'''
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
char *dup_prefix(const char*src,size_t n){
    if(n==SIZE_MAX)return NULL;
    char*buf=(char*)malloc(n+1);if(!buf)return NULL;
    memcpy(buf,src,n);buf[n]='\0';return buf;
}'''),
"v03": ("c", r'''
#include <stddef.h>
#include <stdio.h>
void render_log(char*dst,size_t cap,const char*user){
    snprintf(dst,cap,"[log] %s",user);
}'''),
"v04": ("cpp", r'''
#include <cstddef>
#include <cstdlib>
#include <cstring>
char *make_greeting(const char*name,size_t n){
    char*buf=(char*)malloc(7+n+1);if(!buf)return nullptr;
    std::memcpy(buf,"Hello, ",7);std::memcpy(buf+7,name,n);buf[7+n]='\0';
    return buf;
}'''),
"v05": ("c", r'''
#include <stddef.h>
void bounded_copy(char*dst,size_t cap,const char*src){
    if(cap==0)return;
    size_t i;
    for(i=0;i+1<cap&&src[i]!='\0';i++)dst[i]=src[i];
    dst[i]='\0';
}'''),
"v06": ("cs", r'''
using System;
using System.IO;
public static class Solution{
    public static string ResolveUserFile(string baseDir,string name){
        string root=Path.GetFullPath(baseDir);
        string full=Path.GetFullPath(Path.Combine(root,name));
        string prefix=root.EndsWith(Path.DirectorySeparatorChar.ToString())?root:root+Path.DirectorySeparatorChar;
        return full.StartsWith(prefix,StringComparison.Ordinal)?full:null;
    }
}'''),
}


def main():
    if OUT.exists():
        shutil.rmtree(OUT.parent)
    OUT.mkdir(parents=True)
    ext = {"c": "c", "cpp": "cpp", "cs": "cs"}

    for tid, (lang, code) in REF.items():
        (OUT / f"ref__{tid}.{ext[lang]}").write_text(code.strip() + "\n", encoding="utf-8")

    # traps have no separate fix; the safe original IS the reference
    for tid in ("v07", "v08"):
        src = next((TASKS / f"{tid}*").parent.glob(f"{tid}*/vuln.*"))
        (OUT / f"ref__{tid}{src.suffix}").write_text(src.read_text(encoding="utf-8"),
                                                     encoding="utf-8")

    # vulnerable originals as "model answers"
    for d in sorted(TASKS.glob("v*/")):
        src = next(d.glob("vuln.*"))
        tid = d.name[:3]
        (OUT / f"vulnorig__{tid}{src.suffix}").write_text(
            src.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"wrote {len(list(OUT.glob('*')))} files to {OUT}")
    print("now run: python autograde.py --run _selftest")
    print("expect: ref__* PASS ; vulnorig__v01..v06 FAIL ; vulnorig__v07,v08 PASS")


if __name__ == "__main__":
    main()
